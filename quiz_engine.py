import streamlit as st
import random
import json
import os
from pypdf import PdfReader
from pptx import Presentation
import google.generativeai as genai
import time

# --- Setup ---
st.set_page_config(page_title="Gemini Quiz Engine", layout="wide")
DB_FILE = "science_topics.json"

# --- Backend ---
def load_data():
    if not os.path.exists(DB_FILE):
        return {"Biology": {}, "Chemistry": {}, "Physics": {}}
    with open(DB_FILE, "r") as f:
        return json.load(f)

def save_data(data):
    with open(DB_FILE, "w") as f:
        json.dump(data, f)

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

# --- DYNAMIC MODEL LISTER ---
def get_available_models(api_key):
    """Asks Google: 'What models can this user ACTUALLY use?'"""
    if not api_key: return []
    try:
        genai.configure(api_key=api_key)
        # Get all models
        models = genai.list_models()
        # Only keep the ones that can write text (generateContent)
        valid_models = [m.name for m in models if 'generateContent' in m.supported_generation_methods]
        return valid_models
    except Exception as e:
        return []

def generate_questions_gemini(text_content, api_key, model_name):
    genai.configure(api_key=api_key)
    
    model = genai.GenerativeModel(model_name)
    
    prompt = f"""
    You are a university examiner. Generate 30 rigorous quiz questions.
    
    FORMAT: Raw JSON only. No markdown.
    TYPES: "mcq", "true_false", "blank".
    
    JSON STRUCTURE:
    [
      {{"type": "mcq", "question": "...", "options": ["A) Option 1","B) Option 2"], "answer": "A"}},
      {{"type": "true_false", "question": "...", "options": ["True","False"], "answer": "True"}},
      {{"type": "blank", "question": "The capital of France is _____.", "answer": "Paris"}}
    ]

    TEXT:
    {text_content[:30000]} 
    """

    try:
        response = model.generate_content(prompt)
        cleaned = response.text.strip().replace("```json", "").replace("```", "").replace("json\n", "")
        return json.loads(cleaned)
    except Exception as e:
        st.error(f"❌ Model '{model_name}' failed: {e}")
        return None

# --- Frontend ---
st.title("🎓 Smart Quiz Engine")
data = load_data()

if "quiz_data" not in st.session_state: st.session_state.quiz_data = []
if "score" not in st.session_state: st.session_state.score = 0

# SIDEBAR
with st.sidebar:
    st.header("Settings")
    subject = st.selectbox("Subject", ["Biology", "Chemistry", "Physics"])
    mode = st.radio("Mode", ["Take Quiz", "Add New Topic", "Manage Topics"])
    st.divider()
    api_key = st.text_input("Gemini API Key", type="password")
    
    available_models = []
    if api_key:
        available_models = get_available_models(api_key)
    
    if available_models:
        st.success(f"Found {len(available_models)} active models!")
        selected_model = st.selectbox("Choose AI Model", available_models, index=0)
    else:
        st.warning("Enter Key to see models")
        selected_model = "models/gemini-2.0-flash" 

# LOGIC
if mode == "Add New Topic":
    st.subheader(f"Add {subject} Material")
    name = st.text_input("Topic Name")
    uploaded_file = st.file_uploader("Upload Notes", type=["pdf", "pptx"])
    text_input = st.text_area("Or Paste Text", height=150)
    
    if st.button("Generate Quiz"):
        full_text = ""
        if uploaded_file: full_text += extract_text(uploaded_file)
        if text_input: full_text += "\n" + text_input
            
        if full_text.strip() and api_key:
            with st.spinner(f"🤖 Generating with {selected_model}..."):
                qs = generate_questions_gemini(full_text, api_key, selected_model)
                if qs:
                    data[subject][name] = qs
                    save_data(data)
                    st.success(f"Success! Generated {len(qs)} questions.")
        elif not api_key:
            st.error("Please enter API Key.")
        else:
            st.warning("Please provide text content.")

elif mode == "Take Quiz":
    topics = list(data[subject].keys())
    if topics:
        topic = st.selectbox("Topic", topics)
        if st.button("Start Quiz"):
            st.session_state.quiz_data = random.sample(data[subject][topic], min(10, len(data[subject][topic])))
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
                
                submitted = st.form_submit_button("Submit")
                
                if submitted:
                    score = 0
                    st.write("### 📝 Results:")
                    for i, q in enumerate(st.session_state.quiz_data):
                        u_ans = user_answers.get(i)
                        c_ans = q['answer']
                        is_correct = False
                        
                        if u_ans:
                             # --- IMPROVED GRADING LOGIC ---
                             if q['type'] == 'blank':
                                 if u_ans.lower().strip() in c_ans.lower(): is_correct = True
                             else:
                                 # Smart check: "B) Option" starts with "B"
                                 # We split by ')' to get just the letter
                                 user_letter = u_ans.split(")")[0].strip()
                                 if u_ans == c_ans or user_letter == c_ans: 
                                     is_correct = True
                        
                        if is_correct:
                            score += 1
                            st.success(f"**Question {i+1}: Correct!**")
                        else:
                            st.error(f"**Question {i+1}: Incorrect**")
                            st.write(f"Your Answer: {u_ans}")
                            st.write(f"✅ Correct Answer: **{c_ans}**")
                        st.divider()
                    
                    st.metric("Final Score", f"{score}/{len(st.session_state.quiz_data)}")
                    if score == len(st.session_state.quiz_data):
                        st.balloons()
    else:
        st.info("No quizzes yet.")

elif mode == "Manage Topics":
    for t in list(data[subject].keys()):
        if st.button(f"Delete {t}", key=t):
            del data[subject][t]
            save_data(data)
            st.rerun()
