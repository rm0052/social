import streamlit as st
import json
from groq import Groq
import uuid
from streamlit_js_eval import streamlit_js_eval
from supabase import create_client, Client
from datetime import datetime, timedelta, timezone
import praw
import os
import argparse
import json
import logging
from typing import Any, Dict, List, Optional, AsyncGenerator
import requests
from pydantic import Field
from fastmcp.server.dependencies import get_http_request
from starlette.requests import Request
from starlette.responses import JSONResponse
from fastmcp import FastMCP
from client import get_client
import asyncio

def run_async(coro):
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            return asyncio.create_task(coro)
        else:
            return loop.run_until_complete(coro)
    except RuntimeError:
        return asyncio.run(coro)

# Initialize FastMCP server for Airtable tools
reddit_mcp = FastMCP(name="reddit-mcp-server")

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def get_reddit_client(request: Request) -> Dict[str, str]:
    """Extract Reddit credentials from HTTP headers."""
    # Check for authentication header
    api_key = request.headers.get("X-Api-Key", "")
    if not api_key:
        raise ValueError("Missing required authentication header: X-Api-Key")
    
    # Extract credentials from headers
    client_id = request.headers.get("REDDIT-CLIENT-ID", "")
    client_secret = request.headers.get("REDDIT-CLIENT-SECRET", "")
    refresh_token = request.headers.get("REDDIT-REFRESH-TOKEN", "")
    
    # Validate that all required headers are present
    missing_headers = []
    if not client_id:
        missing_headers.append("REDDIT-CLIENT-ID")
    if not client_secret:
        missing_headers.append("REDDIT-CLIENT-SECRET")
    if not refresh_token:
        missing_headers.append("REDDIT-REFRESH-TOKEN")
    
    if missing_headers:
        raise ValueError(f"Missing required Reddit headers: {', '.join(missing_headers)}")

    # Return the credentials
    return {
        "client_id": client_id,
        "client_secret": client_secret,
        "refresh_token": refresh_token,
        "base_url": "https://oauth.reddit.com"
    }

def get_access_token(credentials: Dict[str, str]) -> str:
    """Get an access token using the refresh token."""
    auth = (credentials['client_id'], credentials['client_secret'])
    data = {
        'grant_type': 'refresh_token',
        'refresh_token': credentials['refresh_token']
    }
    headers = {
        'User-Agent': 'MCP-Reddit-Client/1.0'
    }
    
    response = requests.post(
        'https://www.reddit.com/api/v1/access_token',
        auth=auth,
        data=data,
        headers=headers
    )
    response.raise_for_status()
    return response.json()['access_token']

def make_reddit_request(endpoint: str, credentials: Dict[str, str], params: Optional[Dict[str, Any]] = None) -> requests.Response:
    """Make a GET request to the Reddit API."""
    url = f"{credentials['base_url']}{endpoint}"
    
    # Get an access token using the refresh token
    try:
        access_token = get_access_token(credentials)
        
        # Create headers with authorization using the access token
        headers = {
            "User-Agent": "MCP-Reddit-Client/1.0",
            "Authorization": f"Bearer {access_token}"
        }
        
        # Log the request for debugging
        logger.info(f"Making request to {url} with params: {params}")
        
        response = requests.get(url, headers=headers, params=params)
        response.raise_for_status()
        return response
    except Exception as e:
        logger.error(f"Error making Reddit request: {str(e)}")
        raise

@reddit_mcp.tool()
async def fetch_reddit_hot_threads(subreddit: str, limit: int = 10) -> str:
        """
        Fetch hot threads from a specified subreddit using the Reddit MCP server
        
        Args:
            subreddit: Name of the subreddit (without the 'r/' prefix)
            limit: Maximum number of threads to fetch (default: 10)
            
        Returns:
            String containing the fetched Reddit threads information
        """
        try:
            request: Request = get_http_request()
            client = get_reddit_client(request)
            
            # Make the request to Reddit API
            endpoint = f"/r/{subreddit}/hot"
            params = {"limit": limit}
            
            response = make_reddit_request(endpoint, client, params)
            content = response.json()
            
            # Process the response
            if not content or "data" not in content or "children" not in content["data"]:
                return f"No threads found in r/{subreddit}"
                
            threads = content["data"]["children"]
            result = []
            
            for i, thread in enumerate(threads, 1):
                thread_data = thread["data"]
                title = thread_data.get("title", "No title")
                author = thread_data.get("author", "Unknown")
                score = thread_data.get("score", 0)
                num_comments = thread_data.get("num_comments", 0)
                permalink = thread_data.get("permalink", "")
                url = f"https://www.reddit.com{permalink}"
                
                thread_info = f"{i}. {title}\n   by u/{author} | Score: {score} | Comments: {num_comments}\n   {url}\n"
                result.append(thread_info)
                
            return "\n".join(result)
        except Exception as e:
            error_msg = f"Error fetching Reddit threads: {str(e)}"
            print(error_msg)
            return error_msg

# --- API KEYS ---
groq_client = Groq(api_key=os.getenv("GROQ_API_KEY"))
EMAIL_LOG = "emails.json"
DATA_FILE = "news_data2.json"

# --- Reddit API Setup ---
reddit = praw.Reddit(
    client_id=os.getenv("REDDIT_CLIENT_ID"),
    client_secret=os.getenv("REDDIT_CLIENT_SECRET"),
    username=os.getenv("REDDIT_USERNAME"),
    password=os.getenv("REDDIT_PASSWORD"),
    user_agent="redditnewsbot by u/Recent_Body981"
)

# --- App Setup ---
st.title("Reddit News Chatbot")

if "session_id" not in st.session_state:
    st.session_state["session_id"] = str(uuid.uuid4())
session_id = st.session_state["session_id"]

# --- Save Email Function ---
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

def save_email(email):
    email = email.strip().lower()
    now = datetime.now(timezone.utc).isoformat()

    existing = supabase.table("emails").select("*").eq("email", email).execute()
    if existing.data:
        user = existing.data[0]
        supabase.table("emails").update({
            "last_visit": now,
            "num_visits": user["num_visits"] + 1
        }).eq("email", email).execute()
    else:
        supabase.table("emails").insert([{
            "email": email,
            "first_visit": now,
            "last_visit": now,
            "num_visits": 1
        }]).execute()

# --- Admin Panel (Optional) ---
SECRET_ADMIN_CODE = os.getenv("SECRET_ADMIN_CODE", "letmein")
query_params = st.query_params
admin_code = query_params.get("admin", None)

def show_admin_panel():
    st.title("🔐 Admin Panel")
    if "admin_authenticated" not in st.session_state:
        st.session_state["admin_authenticated"] = False
    if not st.session_state["admin_authenticated"]:
        password = st.text_input("Enter Admin Password", type="password")
        if password == os.getenv("ADMIN_PASSWORD", "qwmnasfjfuifgf"):
            st.session_state["admin_authenticated"] = True
            st.rerun()
        elif password:
            st.error("Incorrect password.")
        st.stop()
    st.success("Welcome Admin!")
    response = supabase.table("emails").select("*").execute()
    if response.data:
        st.json(response.data)
    else:
        st.info("No emails collected.")

# --- Email Login Flow ---
user_id = streamlit_js_eval(js_expressions="window.localStorage.getItem('user_id')", key="get_user_id")
if not user_id:
    if admin_code == SECRET_ADMIN_CODE:
        show_admin_panel()
    email = st.text_input("Enter your email to continue:")
    if email and "@" in email:
        save_email(email)
        streamlit_js_eval(js_expressions=f"window.localStorage.setItem('user_id', '{email}')", key="set_user_id")
        st.success("✅ Thanks! You're now connected.")
    else:
        st.warning("Please enter a valid email to start.")
        st.stop()
else:
    st.success("✅ Welcome back!")
    user_email = st.session_state.get("get_user_id")
    try:
        response = supabase.table("emails").select("email").eq("email", user_email).execute()
        if response.data:
            save_email(user_email)
    except Exception as e:
        st.warning(f"Could not load visit data from Supabase: {e}")

def groq_generate(prompt):
    completion = groq_client.chat.completions.create(
        model="llama-3.1-8b-instant",
        messages=[
            {"role": "system", "content": "You are a helpful assistant."},
            {"role": "user", "content": prompt}
        ],
        temperature=0.3,
        max_tokens=1024,
    )
    return completion.choices[0].message.content

# --- Load and Save News Data ---
def load_news_data():
    if os.path.exists(DATA_FILE):
        with open(DATA_FILE, "r") as f:
            try:
                return json.load(f)
            except json.JSONDecodeError:
                return {}
    return {}

def save_news_data(news_data):
    with open(DATA_FILE, "w") as f:
        json.dump(news_data, f)

news_data = load_news_data()
if session_id not in news_data:
    news_data[session_id] = {"news_articles": "", "news_links": [], "chat_history": []}

st.session_state["news_articles"] = news_data[session_id]["news_articles"]
st.session_state["news_links"] = news_data[session_id]["news_links"]
st.session_state["chat_history"] = news_data[session_id]["chat_history"]

subreddits = ["stocks","investing","pennystocks","Options","SecurityAnalysis","DividendInvesting","cryptocurrency","cryptomarkets","Bitcoin","wallstreetbets"]



# --- Chat History Display ---
st.write("## Chat History")
for q, r in st.session_state["chat_history"]:
    with st.chat_message("user"):
        st.write(q)
    with st.chat_message("assistant"):
        st.write(r)

# --- Chat Input and Answering ---
question = st.chat_input("Type your question and press Enter...")
st.write("Questions or feedback? Email hello@stockdoc.biz.")

if question:
    async def fetch():
        parser = argparse.ArgumentParser(description="Run Reddit MCP Client to interact with Reddit content")
        parser.add_argument(
            "--mcp-localhost-port", type=int, default=8123, help="Localhost port to bind to"
        )
        args = parser.parse_args()
        client = get_client()
        headers = {
                "X-Api-Key": "123",  # Basic API key for authentication
                "REDDIT-CLIENT-ID": "Nq4nwSo-4sQRxPSso70nJQ",
                "REDDIT-CLIENT-SECRET": "jrfgy8_UbQCQ6fMwpINviwDocUoLCg",
                "REDDIT-REFRESH-TOKEN": "197287738010357-satTZRsUCK_69hDZmNCOeYyRmNk3Ww"
            }
        print("Using headers with Reddit credentials (values redacted for security):")
        redacted_headers = {
            k: (v[:5] + "..." if k.startswith("REDDIT-") and v else v) 
            for k, v in headers.items()
        }
        print(f"Headers: {redacted_headers}")
            
        server_url = "http://127.0.0.1:8134/mcp"
        print(f"Connecting to server at: {server_url}")
        
        await client.connect_to_streamable_http_server(
            server_url,
            headers=headers
        )
        print("Connected to server successfully")
        response=await client.chat_loop("wallstreetbets", 5)
        return response
    response = run_async(fetch())
    final_prompt = f"Each link represents a Reddit post. Summarize the content of the post that the question refers to and answer the question. Question: {question} links: {response}"
    final_response=groq_generate(final_prompt)
    st.session_state["chat_history"].append(
        (question, final_response.replace("$", "\\$").replace("provided text", "available information"))
    )
    news_data[session_id]["chat_history"] = st.session_state["chat_history"]
    save_news_data(news_data)
    st.rerun()

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run MCP Streamable HTTP based Reddit server")
    parser.add_argument("--port", type=int, default=8134, help="Localhost port to listen on")
    args = parser.parse_args()

    reddit_mcp.run(transport="streamable-http", host="0.0.0.0", port=args.port)
