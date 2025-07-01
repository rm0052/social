import streamlit as st
import json
from google import genai
import os
import uuid
from streamlit_js_eval import streamlit_js_eval
from datetime import datetime
import praw

# --- API KEYS ---
GENAI_API_KEY = "AIzaSyDFbnYmLQ1Q55jIYYmgQ83sxledB_MgTbw"
EMAIL_LOG = "emails.json"
DATA_FILE = "news_data2.json"

# --- Reddit API Setup ---
reddit = praw.Reddit(
    client_id="qTGIHLm1JS_oC-raKNNNtA",
    client_secret="XnynsOKBktJN1HyRegE5zEZ1GPjWGg",
    username="Recent_Body981",
    password="Cricket$4080",
    user_agent="silverbot by u/Recent_Body981"
)

# --- App Setup ---
st.title("📈 Reddit News Chatbot")

if "session_id" not in st.session_state:
    st.session_state["session_id"] = str(uuid.uuid4())
session_id = st.session_state["session_id"]

# --- Save Email Function ---
def save_email(email):
    email = email.strip().lower()
    now = datetime.utcnow().isoformat()
    if os.path.exists(EMAIL_LOG):
        with open(EMAIL_LOG, "r") as f:
            try:
                email_data = json.load(f)
            except json.JSONDecodeError:
                email_data = {}
    else:
        email_data = {}
    if email in email_data:
        email_data[email]["last_visit"] = now
        email_data[email]["num_visits"] += 1
    else:
        email_data[email] = {
            "first_visit": now,
            "last_visit": now,
            "num_visits": 1
        }
    with open(EMAIL_LOG, "w") as f:
        json.dump(email_data, f, indent=2)

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
    if os.path.exists(EMAIL_LOG):
        with open(EMAIL_LOG, "r") as f:
            try:
                email_data = json.load(f)
            except json.JSONDecodeError:
                st.error("Failed to parse email data.")
                st.stop()
        st.json(email_data)
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
    if os.path.exists(EMAIL_LOG):
        with open(EMAIL_LOG, "r") as f:
            try:
                email_data = json.load(f)
                if user_email in email_data:
                    save_email(user_email)
            except json.JSONDecodeError:
                st.warning("Could not load visit data.")

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

# --- New Reddit Scraper Function ---
from datetime import datetime, timedelta

def scrape_reddit_news():
    subreddits = [
        "stocks", "investing", "pennystocks", "Options", "SecurityAnalysis",
        "DividendInvesting", "cryptocurrency", "cryptomarkets", "Bitcoin"
    ]
    subreddit = reddit.subreddit("+".join(subreddits))
    articles = ""
    links = []

    now = datetime.utcnow()
    cutoff = now - timedelta(days=1)  # 24 hours ago

    for submission in subreddit.new(limit=100):  # fetch more to filter
        post_time = datetime.utcfromtimestamp(submission.created_utc)
        if post_time < cutoff:
            continue
        if not submission.stickied and not submission.over_18:
            title = submission.title.strip()
            url = submission.url
            selftext = submission.selftext.strip()
            articles += f"\n\nTitle: {title}\nURL: {url}\nPosted: {post_time.isoformat()} UTC\nContent: {selftext}\n"
            links.append(url)

    st.session_state["news_articles"] = articles
    st.session_state["news_links"] = links
    news_data[session_id]["news_articles"] = articles
    news_data[session_id]["news_links"] = links
    save_news_data(news_data)


# --- Fetch News Button ---
# if st.button("Fetch latest Reddit news"):
#     st.write("🔍 Fetching Reddit news articles...")
#     scrape_reddit_news()
#     st.write(f"✅ {len(st.session_state['news_links'])} Reddit posts collected.")

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
    if not st.session_state["news_links"]:
        st.warning("⚠️ No articles found. Click 'Fetch latest Reddit news' first.")
    else:
        st.write("🔗 Fetching content from saved Reddit posts...")
        links = st.session_state["news_links"]
        client = genai.Client(api_key=GENAI_API_KEY)

        prompt = f"Answer only yes or no if the question requires specific information from the Reddit posts. Question: {question} links: {links}."
        response = client.models.generate_content(model="gemini-2.0-flash", contents=prompt)
        answer = response.text.strip()

        if answer.lower() == "yes":
            final_prompt = f"Each link represents a Reddit post. Summarize the content of the post that the question refers to. Question: {question} links: {links}"
        else:
            final_prompt = f'''These links are Reddit posts related to finance and cryptocurrency. Today is July 1st. Question: {question}. Respond with the links that are useful: {links}'''

        final_response = client.models.generate_content(
            model="gemini-2.0-flash", contents=final_prompt
        )

        st.session_state["chat_history"].append(
            (question, final_response.text.replace("$", "\\$").replace("provided text", "available information"))
        )
        news_data[session_id]["chat_history"] = st.session_state["chat_history"]
        save_news_data(news_data)
        st.rerun()
