import json
import os
from typing import List, Dict, Any, Optional
from langchain_openai import ChatOpenAI
from langchain_core.prompts import ChatPromptTemplate
from app.config import get_settings

class LocalMapperService:
    """
    Simplified Mapper Service for local Streamlit testing.
    Uses OpenAI to map transactions to a hardcoded Master COA.
    """
    
    # Standard Master COA for testing
    MASTER_COA = [
        # Assets
        {"id": "1000", "category": "Current Assets", "account_name": "Cash and Cash Equivalents", "sub_category": "Cash"},
        {"id": "1100", "category": "Current Assets", "account_name": "Accounts Receivable", "sub_category": "Receivables"},
        {"id": "1200", "category": "Current Assets", "account_name": "Prepaid Expenses", "sub_category": "Prepaids"},
        {"id": "1300", "category": "Fixed Assets", "account_name": "Furniture and Fixtures", "sub_category": "PPE"},
        {"id": "1350", "category": "Fixed Assets", "account_name": "Computer Equipment", "sub_category": "PPE"},
        
        # Liabilities
        {"id": "2000", "category": "Current Liabilities", "account_name": "Accounts Payable", "sub_category": "Payables"},
        {"id": "2100", "category": "Current Liabilities", "account_name": "Credit Cards Payable", "sub_category": "Credit Cards"},
        {"id": "2200", "category": "Long Term Liabilities", "account_name": "Notes Payable", "sub_category": "Debt"},
        
        # Equity
        {"id": "3000", "category": "Equity", "account_name": "Owner's Capital", "sub_category": "Equity"},
        {"id": "3100", "category": "Equity", "account_name": "Retained Earnings", "sub_category": "Equity"},
        
        # Revenue
        {"id": "4000", "category": "Revenue", "account_name": "Sales Revenue", "sub_category": "Income"},
        {"id": "4100", "category": "Revenue", "account_name": "Service Income", "sub_category": "Income"},
        
        # Expenses
        {"id": "5000", "category": "Expenses", "account_name": "Advertising and Marketing", "sub_category": "OpEx"},
        {"id": "5100", "category": "Expenses", "account_name": "Bank Charges and Fees", "sub_category": "OpEx"},
        {"id": "5200", "category": "Expenses", "account_name": "Contract Labor", "sub_category": "OpEx"},
        {"id": "5300", "category": "Expenses", "account_name": "Dues and Subscriptions", "sub_category": "OpEx"},
        {"id": "5400", "category": "Expenses", "account_name": "Insurance", "sub_category": "OpEx"},
        {"id": "5500", "category": "Expenses", "account_name": "Meals and Entertainment", "sub_category": "OpEx"},
        {"id": "5600", "category": "Expenses", "account_name": "Office Supplies", "sub_category": "OpEx"},
        {"id": "5700", "category": "Expenses", "account_name": "Payroll Expenses", "sub_category": "OpEx"},
        {"id": "5800", "category": "Expenses", "account_name": "Professional Fees", "sub_category": "OpEx"},
        {"id": "5900", "category": "Expenses", "account_name": "Rent or Lease", "sub_category": "OpEx"},
        {"id": "6000", "category": "Expenses", "account_name": "Software and Tech", "sub_category": "OpEx"},
        {"id": "6100", "category": "Expenses", "account_name": "Travel", "sub_category": "OpEx"},
        {"id": "6200", "category": "Expenses", "account_name": "Utilities", "sub_category": "OpEx"},
    ]

    def __init__(self):
        settings = get_settings()
        self.llm = ChatOpenAI(
            model=settings.openai_chat_model,
            openai_api_key=settings.openai_api_key,
            temperature=0
        )

    def _build_batch_prompt(self, transactions: List[Dict[str, Any]]) -> str:
        coa_text = json.dumps(self.MASTER_COA, indent=2)
        
        # Minify txs for prompt
        tx_list_text = json.dumps([{
            "id": t['sig'],
            "account": t['tx'].get('raw_account'),
            "desc": t['tx'].get('raw_desc'),
            "vendor": t['tx'].get('vendor'),
            "amount": t['tx'].get('amount')
        } for t in transactions], indent=2)
        
        return f"""
        You are an expert Accountant. Map the following list of transactions to the BEST matching account from the provided Master Chart of Accounts.
        
        MASTER CHART OF ACCOUNTS:
        {coa_text}
        
        TRANSACTIONS TO MAP:
        {tx_list_text}
        
        INSTRUCTIONS:
        1. Analyze each transaction.
        2. Select the single best account from the COA.
        3. Respond with a JSON LIST of objects, one for each transaction.
        
        OUTPUT FORMAT (JSON LIST ONLY):
        [
            {{
                "id": "transaction_id_from_input",
                "mapped_account_id": "ID",
                "mapped_account_name": "Name",
                "category": "Category",
                "confidence": 0.95,
                "reasoning": "Explanation..."
            }},
            ...
        ]
        """

    def map_transactions(self, transactions: List[Dict[str, Any]], progress_callback=None, confidence_threshold=0.85) -> List[Dict[str, Any]]:
        """
        Map a list of transactions using LLM in Batches.
        """
        mapped_results = []
        total = len(transactions)
        
        # Group unique descriptions
        unique_txs = {}
        for t in transactions:
            sig = f"{t.get('raw_account')}|{t.get('raw_desc')}|{t.get('vendor')}"
            if sig not in unique_txs:
                unique_txs[sig] = t
        
        unique_items = [{"sig": sig, "tx": tx} for sig, tx in unique_txs.items()]
        total_unique = len(unique_items)
        
        print(f"Mapping {total_unique} unique patterns from {total} transactions in batches...")
        
        mapping_cache = {}
        
        # PROCESS IN BATCHES
        BATCH_SIZE = 15
        for i in range(0, total_unique, BATCH_SIZE):
            batch = unique_items[i:i+BATCH_SIZE]
            
            try:
                prompt = self._build_batch_prompt(batch)
                response = self.llm.invoke(prompt)
                
                content = response.content.strip()
                if content.startswith('```'):
                    content = content.split('\n', 1)[1].rsplit('```', 1)[0]
                
                batch_results = json.loads(content)
                
                # Map results back to cache
                for res in batch_results:
                    sig_id = res.get('id')
                    if not sig_id: continue
                    
                    # Confidence Check
                    confidence = res.get('confidence', 0.0)
                    if confidence < confidence_threshold:
                        res['suggested_account_name'] = res.get('mapped_account_name')
                        res['suggested_category'] = res.get('category')
                        res['mapped_account_name'] = "Unmapped (Low Confidence)"
                        res['category'] = "Unmapped"
                        res['reasoning'] = f"[Low Confidence: {confidence}] " + res.get('reasoning', '')
                    
                    mapping_cache[sig_id] = res
                    
            except Exception as e:
                # Batch failed
                print(f"Batch {i} failed: {e}")
                for item in batch:
                    mapping_cache[item['sig']] = {
                        "mapped_account_name": "Unmapped (Error)",
                        "category": "Unmapped",
                        "confidence": 0.0,
                        "reasoning": f"Batch Error: {str(e)}"
                    }
            
            if progress_callback:
                progress_callback(min(i + BATCH_SIZE, total_unique), total_unique)

        # Apply mappings back to all transactions
        for t in transactions:
            sig = f"{t.get('raw_account')}|{t.get('raw_desc')}|{t.get('vendor')}"
            mapping = mapping_cache.get(sig, {})
            
            # Merge mapping into transaction
            t_mapped = t.copy()
            t_mapped.update(mapping)
            mapped_results.append(t_mapped)
            
        return mapped_results
