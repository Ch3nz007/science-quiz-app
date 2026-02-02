import streamlit as st
import random
import json
import time
from github import Github, GithubException
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
        if "GITHUB_TOKEN" not in st.secrets:
            st.error("Secrets Error: GITHUB_TOKEN is missing.")
            return None
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
        
        contents = repo.get_contents(FILE_PATH)
        json_content = contents.decoded_content.decode()
        return json.loads(json_content)
    except:
        return {"Biology": {}, "Chemistry": {}, "Physics": {}}

def save_data(data):
    """Updates the JSON file on GitHub"""
    try:
        repo = get_repo()
        if not repo: return
        
        json_str = json.dumps(data, indent=2)
        try:
            contents = repo.get_contents(FILE_PATH)
            repo.update_file(contents.path, "Update Quiz Data", json_str, contents.sha)
        except:
            repo.create_file(FILE_PATH, "Initial Quiz Data", json_str)
    except Exception as e:
        st.error(f"Failed to save to cloud: {e}")

# --- Helper Functions ---
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
    
    # Sanitizer
    safe_text = text_content.replace("\\", "/") 
    
    prompt = f"""
    You are a rigorous university examiner. 
    GOAL: Create a massive "Deep Learning" question bank.
    
    INSTRUCTIONS:
    1. Read the text and identify EVERY SINGLE fact, definition, and concept (major or minor).
    2. For EACH fact found, generate THREE (3) distinct variations of questions:
       - Variation A: Multiple Choice (mcq)
       - Variation B: True/False (true_false)
       - Variation C: Fill in the Blank (blank)
    
    EXAMPLE:
    Concept: "Mitochondria is the powerhouse."
    1. (MCQ) Which organelle...? 
    2. (T/F) The nucleus is the powerhouse...
    3. (Blank) The __________ is the powerhouse...

    QUANTITY: Do NOT stop at the "main" concepts. Cover minor details too. 
    Aim for 60 to 90 total questions (20-30 concepts x 3 variations).
    
    FORMAT: Raw JSON only. No markdown.
    TEXT CONTENT:
    {safe_text} 
    """
    try:
        response = model.generate_content(prompt)
        cleaned = response.text.strip().replace("```json", "").replace("```", "").replace("json\n", "")
        return json.loads(cleaned)
    except Exception as e:
        st.error(f"AI Generation Error: {e}")
        return None

# --- Frontend ---
st.title("🎓 Smart Quiz Engine (Cloud Synced)")

if "quiz_data" not in st.session_state: st.session_state.quiz_data = []
if "score" not in st.session_state: st.session_state.score = 0
if "quiz_active" not in st.session_state: st.session_state.quiz_active = False

with st.spinner("Syncing..."):
    data = load_data()

with st.sidebar:
    st.header("Settings")
    subject = st.selectbox("Subject", ["Biology", "Chemistry", "Physics"])
    mode = st.radio("Mode", ["Take Quiz", "Add New Topic", "Manage Topics"])
    st.divider()
    api_key = st.text_input("Gemini API Key", type="password")
    
    available_models = []
    if api_key: available_models = get_available_models(api_key)
    if available_models:
        st.success(f"Connected!")
        selected_model = st.selectbox("Model", available_models, index=0)
    else:
        selected_model = "models/gemini-2.0-flash"

if mode == "Add New Topic":
    st.subheader(f"Add {subject} Material")
    name = st.text_input("Topic Name")
    uploaded_file = st.file_uploader("Upload Notes", type=["pdf", "pptx"])
    text_input = st.text_area("Paste Text", height=150)
    
    if st.button("Generate & Save"):
        full_text = ""
        if uploaded_file: full_text += extract_text(uploaded_file)
        if text_input: full_text += "\n" + text_input
            
        if full_text.strip() and api_key:
            with st.spinner(f"Generating Variations..."):
                qs = generate_questions_gemini(full_text, api_key, selected_model)
                if qs:
                    if subject not in data: data[subject] = {}
                    data[subject][name] = qs
                    save_data(data)
                    st.success(f"Saved {len(qs)} questions (3 variations per fact)!")
                    time.sleep(2)
                    st.rerun()
        else:
            st.warning("Missing API Key or Content")

elif mode == "Take Quiz":
    if subject not in data: data[subject] = {}
    topics = list(data[subject].keys())
    
    if topics:
        topic = st.selectbox("Topic", topics)
        questions = data[subject][topic]
        
        if len(questions) > 0:
            q_limit = st.slider("Number of Questions", 1, len(questions), min(10, len(questions)))
            
            if st.button("Start New Quiz"):
                st.session_state.quiz_data = random.sample(questions, q_limit)
                st.session_state.score = 0
                st.session_state.quiz_active = True
                st.rerun()

            if st.session_state.quiz_active and st.session_state.quiz_data:
                with st.form("my_quiz_form"):
                    user_answers = {}
                    for i, q in enumerate(st.session_state.quiz_data):
                        st.write(f"**{i+1}. {q['question']}**")
                        widget_key = f"q_{i}"
                        
                        if q['type'] == 'mcq':
                            user_answers[i] = st.radio("Select:", q.get('options', []), key=widget_key, index=None)
                        elif q['type'] == 'true_false':
                            # Force True/False options even if AI forgot them
                            user_answers[i] = st.radio("True/False:", ["True", "False"], key=widget_key, index=None)
                        else:
                            user_answers[i] = st.text_input("Answer:", key=widget_key)
                        st.divider()
                    
                    submitted = st.form_submit_button("Submit Quiz")
                    
                    if submitted:
                        score = 0
                        st.write("### 📝 Results:")
                        for i, q in enumerate(st.session_state.quiz_data):
                            u_ans = user_answers.get(i)
                            c_ans = q['answer']
                            is_correct = False
                            
                            if u_ans:
                                if q['type'] == 'blank':
                                    if str(u_ans).lower().strip() in str(c_ans).lower(): is_correct = True
                                else:
                                    user_str = str(u_ans).split(")")[0].strip()
                                    target_str = str(c_ans).split(")")[0].strip()
                                    if str(u_ans) == str(c_ans) or user_str == target_str:
                                        is_correct = True
                            
                            if is_correct:
                                score += 1
                                st.success(f"**Q{i+1}: Correct!**")
                            else:
                                st.error(f"**Q{i+1}: Incorrect**")
                                st.write(f"Your Answer: {u_ans}")
                                st.write(f"Correct Answer: {c_ans}")
                            st.divider()
                            
                        st.metric("Final Score", f"{score}/{len(st.session_state.quiz_data)}")
                        if st.form_submit_button("Take Another Quiz"):
                            st.session_state.quiz_active = False
                            st.rerun()
        else:
            st.warning("Topic has 0 questions.")
    else:
        st.info("No topics found. Add one!")

elif mode == "Manage Topics":
    if subject in data:
        for t in list(data[subject].keys()):
            col1, col2 = st.columns([4,1])
            with col1: st.write(f"**{t}** ({len(data[subject][t])} qs)")
            with col2:
                if st.button("Delete", key=f"del_{t}"):
                    del data[subject][t]
                    save_data(data)
                    st.rerun()
