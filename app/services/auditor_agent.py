"""
AceCPAs Backend - Auditor Agent Service
Anomaly detection and automated question generation for open items.
"""
import re
from decimal import Decimal
from typing import List, Dict, Any, Optional

from langchain_openai import ChatOpenAI

from app.config import get_settings
from app.database import get_supabase_admin_client


class FlagReason:
    """Constants for flag reasons."""
    KEYWORD_PERSONAL = "keyword_personal"
    KEYWORD_CASH = "keyword_cash"
    KEYWORD_VENMO = "keyword_venmo"
    KEYWORD_REIMBURSEMENT = "keyword_reimbursement"
    CAPEX_THRESHOLD = "capex_threshold"
    LOW_CONFIDENCE = "low_confidence"
    UNUSUAL_AMOUNT = "unusual_amount"


class AuditorAgentService:
    """
    Service for auditing GL transactions.
    Performs:
    1. Deterministic rule-based anomaly detection
    2. LLM-powered professional question generation
    """
    
    # Keyword patterns for flagging
    PERSONAL_KEYWORDS = [
        r'\bvenmo\b', r'\bcash\b', r'\breimbursement\b', r'\bpersonal\b',
        r'\batm\b', r'\bwithdrawal\b', r'\btransfer\b', r'\bzelle\b',
        r'\bpaypal\b', r'\bcashapp\b'
    ]
    
    # Categories that trigger CapEx review
    CAPEX_REVIEW_CATEGORIES = [
        'Repairs & Maintenance',
        'IT Equipment',
        'Property & Equipment'
    ]
    
    def __init__(self):
        self.settings = get_settings()
        self.client = get_supabase_admin_client()
        self.llm = ChatOpenAI(
            model=self.settings.openai_chat_model,
            openai_api_key=self.settings.openai_api_key,
            temperature=0.3  # Slightly higher for more natural language
        )
    
    def detect_keyword_flags(
        self,
        transaction: Dict[str, Any]
    ) -> Optional[Dict[str, Any]]:
        """
        Check transaction for flagged keywords in description/vendor.
        
        Returns:
            Flag dict with reason and matched keyword, or None
        """
        text_to_check = ' '.join([
            str(transaction.get('raw_desc', '')),
            str(transaction.get('vendor', '')),
            str(transaction.get('raw_account', ''))
        ]).lower()
        
        for pattern in self.PERSONAL_KEYWORDS:
            match = re.search(pattern, text_to_check, re.IGNORECASE)
            if match:
                keyword = match.group()
                
                # Determine specific flag reason
                if 'venmo' in keyword:
                    reason = FlagReason.KEYWORD_VENMO
                elif keyword in ['cash', 'atm', 'withdrawal']:
                    reason = FlagReason.KEYWORD_CASH
                elif 'reimbursement' in keyword:
                    reason = FlagReason.KEYWORD_REIMBURSEMENT
                else:
                    reason = FlagReason.KEYWORD_PERSONAL
                
                return {
                    'reason': reason,
                    'matched_keyword': keyword,
                    'description': f"Transaction contains flagged keyword: '{keyword}'"
                }
        
        return None
    
    def detect_capex_flags(
        self,
        transaction: Dict[str, Any],
        coa_name: str
    ) -> Optional[Dict[str, Any]]:
        """
        Check for potential CapEx misclassification.
        Flags R&M transactions above threshold.
        
        Returns:
            Flag dict or None
        """
        # Check if mapped to a CapEx-review category
        is_review_category = any(
            cat.lower() in coa_name.lower()
            for cat in self.CAPEX_REVIEW_CATEGORIES
        )
        
        if not is_review_category:
            return None
        
        # Check amount threshold
        amount = abs(Decimal(str(transaction.get('amount', 0))))
        
        if amount > self.settings.capex_threshold:
            return {
                'reason': FlagReason.CAPEX_THRESHOLD,
                'amount': float(amount),
                'threshold': self.settings.capex_threshold,
                'description': f"Large {coa_name} expense (${amount:,.2f}) may require capitalization review"
            }
        
        return None
    
    def detect_low_confidence(
        self,
        transaction: Dict[str, Any],
        threshold: float = 0.7
    ) -> Optional[Dict[str, Any]]:
        """
        Flag transactions with low mapping confidence.
        
        Returns:
            Flag dict or None
        """
        confidence = transaction.get('confidence')
        
        if confidence is not None and confidence < threshold:
            return {
                'reason': FlagReason.LOW_CONFIDENCE,
                'confidence': confidence,
                'threshold': threshold,
                'description': f"Low confidence mapping ({confidence:.0%}). Manual review recommended."
            }
        
        return None
    
    def scan_transaction(
        self,
        transaction: Dict[str, Any],
        coa_name: str = ''
    ) -> List[Dict[str, Any]]:
        """
        Run all anomaly detection rules on a transaction.
        
        Returns:
            List of flag dicts
        """
        flags = []
        
        # 1. Keyword detection
        keyword_flag = self.detect_keyword_flags(transaction)
        if keyword_flag:
            flags.append(keyword_flag)
        
        # 2. CapEx threshold
        if coa_name:
            capex_flag = self.detect_capex_flags(transaction, coa_name)
            if capex_flag:
                flags.append(capex_flag)
        
        # 3. Low confidence
        confidence_flag = self.detect_low_confidence(transaction)
        if confidence_flag:
            flags.append(confidence_flag)
        
        return flags
    
    def generate_question(
        self,
        transaction: Dict[str, Any],
        flag: Dict[str, Any],
        deal_context: Optional[str] = None
    ) -> str:
        """
        Generate a professional client question using LLM.
        
        Args:
            transaction: The flagged transaction
            flag: The flag details
            deal_context: Optional context about the client (e.g., industry)
        
        Returns:
            Generated question text
        """
        context = deal_context or "a business client"
        
        prompt = f"""You are a professional accountant drafting a client inquiry email.

CONTEXT:
- Client: {context}
- Transaction Vendor: {transaction.get('vendor', 'N/A')}
- Transaction Amount: ${abs(Decimal(str(transaction.get('amount', 0)))):,.2f}
- Transaction Description: {transaction.get('raw_desc', 'N/A')}
- Transaction Date: {transaction.get('raw_date', 'N/A')}
- Category: {transaction.get('coa_name', 'Uncategorized')}

ISSUE FLAGGED:
{flag.get('description', flag.get('reason', 'Unknown issue'))}

TASK:
Draft a polite, professional email query asking the client for clarification or documentation.
Keep it concise (2-3 sentences maximum).
Be specific about what documentation or clarification is needed.
Do not include email headers/footers, just the core question.

RESPONSE:"""

        response = self.llm.invoke(prompt)
        return response.content.strip()
    
    def create_open_item(
        self,
        deal_id: str,
        transaction: Dict[str, Any],
        flag: Dict[str, Any],
        question_text: str
    ) -> Dict[str, Any]:
        """
        Create an open item in the database.
        
        Returns:
            Created open item record
        """
        open_item = {
            'deal_id': deal_id,
            'transaction_id': transaction['id'],
            'flag_reason': flag.get('reason'),
            'question_text': question_text,
            'status': 'draft'
        }
        
        result = self.client.table("open_items").insert(open_item).execute()
        return result.data[0] if result.data else None
    
    def process_deal(
        self,
        deal_id: str,
        generate_questions: bool = True
    ) -> Dict[str, Any]:
        """
        Run auditor on all mapped transactions for a deal.
        
        Args:
            deal_id: UUID of the deal
            generate_questions: Whether to generate LLM questions
        
        Returns:
            Processing stats
        """
        stats = {
            'transactions_scanned': 0,
            'flagged_count': 0,
            'questions_generated': 0,
            'flags_by_reason': {},
            'errors': []
        }
        
        # Get deal context for better questions
        deal_result = self.client.table("deals").select("*").eq("id", deal_id).single().execute()
        deal = deal_result.data
        deal_context = f"{deal.get('client_name', 'Client')} ({deal.get('industry', 'business')})" if deal else None
        
        # Get all transactions with their COA mappings
        result = self.client.table("gl_transactions").select(
            "*, master_coa(account_name, category)"
        ).eq("deal_id", deal_id).execute()
        
        transactions = result.data or []
        
        for transaction in transactions:
            try:
                stats['transactions_scanned'] += 1
                
                # Get COA name if mapped
                coa = transaction.get('master_coa')
                coa_name = coa.get('account_name', '') if coa else ''
                
                # Add coa_name to transaction for LLM context
                transaction['coa_name'] = coa_name
                
                # Scan for anomalies
                flags = self.scan_transaction(transaction, coa_name)
                
                for flag in flags:
                    stats['flagged_count'] += 1
                    
                    # Track by reason
                    reason = flag.get('reason', 'unknown')
                    stats['flags_by_reason'][reason] = stats['flags_by_reason'].get(reason, 0) + 1
                    
                    # Generate question if enabled
                    question_text = None
                    if generate_questions:
                        try:
                            question_text = self.generate_question(
                                transaction, flag, deal_context
                            )
                            stats['questions_generated'] += 1
                        except Exception as e:
                            stats['errors'].append({
                                'transaction_id': transaction['id'],
                                'error': f"Question generation failed: {str(e)}"
                            })
                            question_text = f"Please provide documentation or clarification for this transaction: {flag.get('description', 'Flagged for review')}"
                    else:
                        question_text = flag.get('description', 'Transaction flagged for review')
                    
                    # Create open item
                    self.create_open_item(
                        deal_id=deal_id,
                        transaction=transaction,
                        flag=flag,
                        question_text=question_text
                    )
                    
            except Exception as e:
                stats['errors'].append({
                    'transaction_id': transaction.get('id'),
                    'error': str(e)
                })
        
        return stats
