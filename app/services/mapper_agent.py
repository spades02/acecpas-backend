"""
AceCPAs Backend - Mapper Agent Service
AI-powered COA mapping using LangGraph.
Extracts unique accounts from GL transactions and maps them to Master COA.
"""
import json
import logging
import uuid
from typing import List, Dict, Any, Optional, TypedDict
from operator import add

from langchain_openai import ChatOpenAI, OpenAIEmbeddings
from langgraph.graph import StateGraph, END
import pandas as pd

from app.config import get_settings
from app.database import get_supabase_admin_client

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class AccountState(TypedDict):
    """State for the mapper agent graph processing a single account."""
    deal_id: str
    organization_id: str
    client_account_id: str
    original_account: str
    description: str
    
    # Mapping results
    embedding: Optional[List[float]]
    matched_coa_id: Optional[str]
    matched_coa_name: Optional[str]
    confidence: float
    reasoning: Optional[str]
    
    # Flags
    needs_llm: bool
    error: Optional[str]
    
    # RAG Context
    similar_examples: Optional[List[Dict[str, Any]]]


class MapperAgentService:
    """
    Service for AI-powered COA mapping.
    1. Extracts unique accounts from gl_transactions -> client_accounts
    2. Maps client_accounts -> account_mappings using Vector Search + LLM
    """
    
    def __init__(self):
        self.settings = get_settings()
        self.embeddings = OpenAIEmbeddings(
            model=self.settings.openai_embedding_model or "text-embedding-3-small",
            openai_api_key=self.settings.openai_api_key
        )
        self.llm = ChatOpenAI(
            model=self.settings.openai_chat_model or "gpt-4-turbo-preview",
            openai_api_key=self.settings.openai_api_key,
            temperature=0
        )
        self.client = get_supabase_admin_client()
        self._coa_cache = None

    def _get_coa_list(self) -> List[Dict[str, Any]]:
        """Get and cache the master COA list."""
        if self._coa_cache is None:
            # Fetch essential fields for prompting
            result = self.client.table("master_coa").select("id, account_code, account_name, category, subcategory, description").eq("is_active", True).execute()
            self._coa_cache = result.data or []
        return self._coa_cache

    def extract_unique_accounts(self, deal_id: str) -> int:
        """
        Scans gl_transactions for the deal, extracts unique accounts, 
        and updates valid client_accounts table.
        """
        logger.info(f"Extracting unique accounts for deal {deal_id}")
        
        # 1. Fetch transactions 
        dataset = self.client.table("gl_transactions").select("deal_id, organization_id, account_name, description, vendor_name, amount").eq("deal_id", deal_id).execute()
        
        if not dataset.data:
            logger.info("No transactions found.")
            return 0
            
        df = pd.DataFrame(dataset.data)
        
        # If 'account_name' is missing/null, fill with "Unknown"
        df['account_name'] = df['account_name'].fillna("Unknown Account")
        
        # 2. Group by account_name
        grouped = df.groupby('account_name').agg({
            'deal_id': 'first',
            'organization_id': 'first', # Get org_id from data
            'description': lambda x: ' | '.join(set([str(s) for s in x if s]))[:500], # Sample descriptions
            'amount': ['count', lambda x: x.abs().sum()]
        }).reset_index()
        
        # Flatten columns
        grouped.columns = ['original_account_string', 'deal_id', 'organization_id', 'description', 'transaction_count', 'total_amount']
        
        # Explicit column mapping to match client_accounts EXACTLY
        # client_accounts: id, deal_id, organization_id, original_account_string, description, created_at, updated_at
        # We also need to be careful about total_amount (it might not be in client_accounts schema if inspection was right?)
        # Double check inspection: ['id', 'deal_id', 'organization_id', 'original_account_string', ... 'transaction_count', 'total_amount']
        # Yes, it has total_amount.
        
        accounts_to_upsert = grouped.to_dict('records')
        
        # 3. Upsert into client_accounts
        if accounts_to_upsert:
            logger.info(f"Upserting {len(accounts_to_upsert)} client accounts")
            self.client.table("client_accounts").upsert(
                accounts_to_upsert, 
                on_conflict="deal_id,original_account_string"
            ).execute()
            
        return len(accounts_to_upsert)

    def generate_embedding(self, text: str) -> List[float]:
        return self.embeddings.embed_query(text)

    def _build_llm_prompt(self, account_info: str, coa_context: str, similar_examples: List[Dict] = None) -> str:
        
        examples_text = ""
        if similar_examples:
            examples_text = "\nSIMILAR HISTORICAL MAPPINGS (Strong hints):\n"
            for ex in similar_examples:
                examples_text += f"- Input: {ex['account_name']} | {ex['description']} | {ex['vendor_name']} -> Mapped to: {ex['correct_coa_name']} ({ex['correct_category']}) [Similarity: {ex['similarity']:.2f}]\n"
        
        return f"""You are an Expert Accountant. Map this client account to the Master Chart of Accounts.

CLIENT ACCOUNT:
{account_info}

{examples_text}

MASTER CHART OF ACCOUNTS (Subset):
{coa_context}

INSTRUCTIONS:
1. Select the BEST matching Master COA account.
2. If uncertain, choose 'Unmapped' or the closest category generic bucket.
3. Provide a confidence score (0-100).
4. IMPORTANT: For "master_account_id", use the UUID of the account, NOT the account code.
5. Trust the historical mappings if the similarity is high (>0.85).

RESPONSE FORMAT (JSON):
{{
    "master_account_id": "UUID",
    "confidence": 85,
    "reasoning": "Explanation..."
}}
"""

    # --- GRAPH NODES ---
    
    def node_embed_and_search(self, state: AccountState) -> AccountState:
        """Generate embedding and search vector store."""
        text = f"{state['original_account']} {state['description']}"
        embedding = self.generate_embedding(text)
        
        # Update client_account with embedding
        self.client.table("client_accounts").update({
            "embedding": embedding
        }).eq("id", state['client_account_id']).execute()

        # Search for similar examples in Golden Data
        similar_examples = []
        try:
            rpc_params = {
                "query_embedding": embedding,
                "match_threshold": 0.5, # Retrieve broadly, filter in prompt
                "match_count": 5
            }
            # Note: Ensure 'match_golden_mappings' function exists in DB
            response = self.client.rpc("match_golden_mappings", rpc_params).execute()
            if response.data:
                similar_examples = response.data
                logger.info(f"Found {len(similar_examples)} similar examples for {state['original_account']}")
        except Exception as e:
            logger.error(f"Vector search failed: {e}")
            
        return {**state, 'embedding': embedding, 'needs_llm': True, 'similar_examples': similar_examples}

    def node_llm_map(self, state: AccountState) -> AccountState:
        """Use LLM to classify."""
        coa_list = self._get_coa_list()
        
        coa_text = json.dumps([{
            'id': c['id'], 
            'code': c['account_code'], 
            'name': c['account_name'],
            'category': c.get('category')
        } for c in coa_list], indent=0)
        
        account_info = f"Account: {state['original_account']}\nDescription Context: {state['description']}"
        
        try:
            prompt = self._build_llm_prompt(account_info, coa_text, state.get('similar_examples'))
            response = self.llm.invoke(prompt)
            content = response.content.replace('```json', '').replace('```', '').strip()
            result = json.loads(content)
            
            return {
                **state,
                'matched_coa_id': result.get('master_account_id'),
                'confidence': result.get('confidence', 0),
                'reasoning': result.get('reasoning'),
            }
        except Exception as e:
            logger.error(f"LLM Mapping error: {e}")
            return {**state, 'error': str(e)}

    def build_graph(self):
        workflow = StateGraph(AccountState)
        workflow.add_node("embed", self.node_embed_and_search)
        workflow.add_node("llm", self.node_llm_map)
        
        workflow.set_entry_point("embed")
        workflow.add_edge("embed", "llm")
        workflow.add_edge("llm", END)
        
        return workflow.compile()

    def process_account(self, account: Dict[str, Any]):
        """Run workflow for a single client account."""
        app = self.build_graph()
        
        initial_state: AccountState = {
            'deal_id': account['deal_id'],
            'organization_id': account['organization_id'],
            'client_account_id': account['id'],
            'original_account': account['original_account_string'],
            'description': account.get('description', ''),
            'embedding': None,
            'matched_coa_id': None,
            'matched_coa_name': None,
            'confidence': 0,
            'reasoning': None,
            'needs_llm': False,
            'error': None,
            'similar_examples': []
        }
        
        final_state = app.invoke(initial_state)
        
        if final_state.get('matched_coa_id'):
            # Validate master_account_id is a UUID (LLM might return account code like '2200')
            matched_id = final_state['matched_coa_id']
            try:
                # Check if it's strictly a UUID string
                val = uuid.UUID(str(matched_id))
            except ValueError:
                # Returned value is not a UUID, likely an account code. Look up correct ID.
                # Use cached COA list to find the ID for this code
                coa_list = self._get_coa_list()
                found_coa = next((c for c in coa_list if str(c['account_code']) == str(matched_id)), None)
                if found_coa:
                    matched_id = found_coa['id']
                else:
                    logger.warning(f"LLM returned invalid ID/Code '{matched_id}' which could not be resolved.")
                    matched_id = None 

            if matched_id:
                # Save to account_mappings
                mapping_data = {
                    'deal_id': final_state['deal_id'],
                    'organization_id': final_state['organization_id'],
                    'client_account_id': final_state['client_account_id'],
                    'master_account_id': matched_id,
                    'confidence_score': int(final_state['confidence']),
                    'ai_reasoning': final_state['reasoning'],
                    'approval_status': 'green' if final_state['confidence'] > 90 else 'yellow'
                }
                
                # Check existing
                existing = self.client.table("account_mappings")\
                    .select("id")\
                    .eq("client_account_id", final_state['client_account_id'])\
                    .execute()
                    
                if existing.data:
                    self.client.table("account_mappings").update(mapping_data).eq("id", existing.data[0]['id']).execute()
                else:
                    self.client.table("account_mappings").insert(mapping_data).execute()

    def process_deal(self, deal_id: str, reprocess_low_confidence: bool = False, confidence_threshold: float = 0.9):
        """Main entry point: Extract then Map."""
        logger.info(f"Starting Mapper for deal {deal_id}")
        
        # Step 1: Extraction
        self.extract_unique_accounts(deal_id)
        
        # Step 2: Fetch Accounts to Map
        accounts_res = self.client.table("client_accounts").select("*, account_mappings(id)").eq("deal_id", deal_id).execute()
        accounts = accounts_res.data or []
        
        processed = 0
        for acc in accounts:
            # If already mapped and not reprocessing, skip
            if acc.get('account_mappings') and len(acc['account_mappings']) > 0 and not reprocess_low_confidence:
                continue
                
            self.process_account(acc)
            processed += 1
            
        logger.info(f"Mapper finished. Processed {processed} accounts.")
        return {"extracted": True, "mapped_count": processed}
