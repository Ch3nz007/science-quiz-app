import streamlit as st
import random
import json
import time
from github import Github, GithubException # We use this to talk to the Cloud
import google.generativeai as genai
from pypdf import PdfReader
from pptx import Presentation

# --- Setup ---
st.set_page_config(page_title="Gemini Quiz Engine", layout="wide")

# ⚠️ CHANGE THIS TO YOUR EXACT REPO NAME
REPO_KEY = "Ch3nz007/science-quiz-app"
FILE_PATH = "science_topics.json"

# --- Cloud Backend (GitHub) ---
def get_repo():
    """Connects to your GitHub Repository"""
    try:
        token = st.secrets["GITHUB_TOKEN"]
        g = Github(token)
        return g.get_repo(REPO_KEY)
    except Exception as e:
        st.error(f"GitHub Connection Error: {e}")
        return None

def load_data():
    """Reads the JSON file directly from GitHub"""
    try:
        repo = get_repo()
        if not repo: return {"Biology": {}, "Chemistry": {}, "Physics": {}}
        
        # Get the file content
        contents = repo.get_contents(FILE_PATH)
        json_content = contents.decoded_content.decode()
        return json.loads(json_content)
    except:
        # If file doesn't exist yet, return empty database
        return {"Biology": {}, "Chemistry": {}, "Physics": {}}

def save_data(data):
    """Updates the JSON file on GitHub"""
    try:
        repo = get_repo()
        if not repo: return
        
        json_str = json.dumps(data, indent=2)
        
        try:
            # Try to fetch the file to get its 'sha' ID (needed for update)
            contents = repo.get_contents(FILE_PATH)
            repo.update_file(contents.path, "Update Quiz Data", json_str, contents.sha)
        except:
            # If file not found, create it
            repo.create_file(FILE_PATH, "Initial Quiz Data", json_str)
            
    except Exception as e:
        st.error(f"Failed to save to cloud: {e}")

# --- Helper Functions (Same as before) ---
def extract_text(uploaded_file):
    text = ""
    try:
        if uploaded_file.name.endswith('.pdf'):
            reader = PdfReader(uploaded_file)
            for page in reader.pages: text += page.extract_text() + "\n"
        elif uploaded_file.name.endswith('.pptx'):
            prs = Presentation(uploaded_file)
            for slide in prs.slides:
                for shape in slide.shapes:
                    if hasattr(shape, "text"): text += shape.text + "\n"
    except: return None
    return text

def get_available_models(api_key):
    if not api_key: return []
    try:
        genai.configure(api_key=api_key)
        models = genai.list_models()
        return [m.name for m in models if 'generateContent' in m.supported_generation_methods]
    except: return []

def generate_questions_gemini(text_content, api_key, model_name):
    genai.configure(api_key=api_key)
    model = genai.GenerativeModel(model_name)
    
    # --- SANITIZE INPUT ---
    # This prevents the "Invalid \escape" crash
    safe_text = text_content.replace("\\", "/") 
    
    prompt = f"""
    You are a rigorous university examiner. 
    GOAL: Create a comprehensive question bank covering EVERY key fact.
    QUANTITY: Aim for 50-80 questions.
    FORMAT: Raw JSON only. No markdown.
    TYPES: "mcq", "true_false", "blank".
    JSON STRUCTURE: [ {{"type": "mcq", "question": "...", "options": ["A) X","B) Y"], "answer": "A"}} ]
    TEXT: {safe_text} 
    """
    try:
        response = model.generate_content(prompt)
        cleaned = response.text.strip().replace("```json", "").replace("```", "").replace("json\n", "")
        return json.loads(cleaned)
    except Exception as e:
        st.error(f"AI Error: {e}")
        return None

# --- Frontend ---
st.title("🎓 Smart Quiz Engine (Cloud Synced)")

# Initialize Session State
if "quiz_data" not in st.session_state: st.session_state.quiz_data = []
if "score" not in st.session_state: st.session_state.score = 0

# Load Data from Cloud
with st.spinner("Connecting to Cloud Database..."):
    data = load_data()

# SIDEBAR
with st.sidebar:
    st.header("Settings")
    subject = st.selectbox("Subject", ["Biology", "Chemistry", "Physics"])
    mode = st.radio("Mode", ["Take Quiz", "Add New Topic", "Manage Topics"])
    st.divider()
    api_key = st.text_input("Gemini API Key", type="password")
    
    # Model Selector
    available_models = []
    if api_key: available_models = get_available_models(api_key)
    if available_models:
        st.success(f"Connected!")
        selected_model = st.selectbox("Model", available_models, index=0)
    else:
        selected_model = "models/gemini-2.0-flash"

# LOGIC
if mode == "Add New Topic":
    st.subheader(f"Add {subject} Material")
    name = st.text_input("Topic Name")
    uploaded_file = st.file_uploader("Upload Notes", type=["pdf", "pptx"])
    text_input = st.text_area("Paste Text", height=150)
    
    if st.button("Generate & Save to Cloud"):
        full_text = ""
        if uploaded_file: full_text += extract_text(uploaded_file)
        if text_input: full_text += "\n" + text_input
            
        if full_text.strip() and api_key:
            with st.spinner(f"Generating questions & syncing to GitHub..."):
                qs = generate_questions_gemini(full_text, api_key, selected_model)
                if qs:
                    data[subject][name] = qs
                    save_data(data) # This saves to GitHub now!
                    st.success(f"Success! {len(qs)} questions saved to the cloud for everyone.")
                    time.sleep(2)
                    st.rerun()
        else:
            st.warning("Needs API Key and Content.")

elif mode == "Take Quiz":
    topics = list(data[subject].keys())
    if topics:
        topic = st.selectbox("Topic", topics)
        if len(data[subject][topic]) > 0:
            q_limit = st.slider("Count", 1, len(data[subject][topic]), min(10, len(data[subject][topic])))
            
            if st.button("Start Quiz"):
                st.session_state.quiz_data = random.sample(data[subject][topic], q_limit)
                st.session_state.score = 0
                
            if st.session_state.quiz_data:
                with st.form("quiz"):
                    user_answers = {}
                    for i, q in enumerate(st.session_state.quiz_data):
                        st.write(f"**{i+1}. {q['question']}**")
                        if q['type'] == 'mcq':
                            user_answers[i] = st.radio("Select:", q['options'], key=i, index=None)
                        elif q['type'] == 'true_false':
                            user_answers[i] = st.radio("True/False:", q['options'], key=i, index=None)
                        else:
                            user_answers[i] = st.text_input("Answer:", key=i)
                        st.divider()
                    
                    if st.form_submit_button("Submit"):
                        score = 0
                        for i, q in enumerate(st.session_state.quiz_data):
                            u_ans = user_answers.get(i)
                            c_ans = q['answer']
                            is_correct = False
                            if u_ans:
                                 if q['type'] == 'blank':
                                     if u_ans.lower().strip() in c_ans.lower(): is_correct = True
                                 else:
                                     # Smart check
                                     user_letter = u_ans.split(")")[0].strip()
                                     if u_ans == c_ans or user_letter == c_ans: is_correct = True
                            if is_correct: score += 1
                            else: st.error(f"Q{i+1} Wrong. Correct: {c_ans}")
                        
                        st.metric("Score", f"{score}/{len(st.session_state.quiz_data)}")
    else:
        st.info("No quizzes found in the cloud.")

elif mode == "Manage Topics":
    for t in list(data[subject].keys()):
        col1, col2 = st.columns([4,1])
        with col1: st.write(f"**{t}** ({len(data[subject][t])} qs)")
        with col2:
            if st.button("Delete", key=t):
                del data[subject][t]
                with st.spinner("Deleting from Cloud..."):
                    save_data(data)
                st.rerun()
