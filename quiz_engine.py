import streamlit as st
import spacy
import random
import json
import os
from pypdf import PdfReader
from pptx import Presentation
import google.generativeai as genai

# --- Setup & Configuration ---
st.set_page_config(page_title="Gemini Quiz Engine", layout="wide")

# --- SPACY DOWNLOADER (With Loading Bar) ---
@st.cache_resource
def load_nlp():
    try:
        return spacy.load("en_core_web_sm")
    except OSError:
        # If model is missing, download it with a visual spinner
        with st.spinner("Downloading AI Brain (this takes 1 minute)..."):
            from spacy.cli import download
            download("en_core_web_sm")
            return spacy.load("en_core_web_sm")

nlp = load_nlp()
DB_FILE = "science_topics.json"

# --- Backend Logic ---

def load_data():
    # Streamlit Cloud resets files on reboot, so we handle missing files gracefully
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
            for page in reader.pages:
                text += page.extract_text() + "\n"
        elif uploaded_file.name.endswith('.pptx'):
            prs = Presentation(uploaded_file)
            for slide in prs.slides:
                for shape in slide.shapes:
                    if hasattr(shape, "text"):
                        text += shape.text + "\n"
    except Exception:
        return None
    return text

# --- SELF-HEALING AI MODEL SELECTOR ---
def get_working_model_name(api_key):
    genai.configure(api_key=api_key)
    try:
        models = genai.list_models()
        for m in models:
            if 'generateContent' in m.supported_generation_methods:
                if 'flash' in m.name: return m.name
                if 'pro' in m.name: return m.name
        return "models/gemini-pro" # Fallback
    except Exception:
        return None

# --- GENERATION LOGIC ---
def generate_questions_gemini(text_content, api_key):
    model_name = get_working_model_name(api_key)
    if not model_name:
        st.error("❌ API Key Error. Please check your key.")
        return []
    
    genai.configure(api_key=api_key)
    model = genai.GenerativeModel(model_name)
    
    prompt = f"""
    Generate 30-40 rigorous quiz questions (MCQ, True/False, Blanks) from the text below.
    Return ONLY raw JSON.
    
    JSON FORMAT:
    [
      {{"type": "mcq", "question": "...", "options": ["A","B"], "answer": "A"}},
      {{"type": "true_false", "question": "...", "options": ["True","False"], "answer": "True"}}
    ]

    TEXT:
    {text_content[:15000]} 
    """
    try:
        response = model.generate_content(prompt)
        cleaned = response.text.strip().replace("```json", "").replace("```", "")
        return json.loads(cleaned)
    except Exception as e:
        st.error(f"AI Error: {e}")
        return []

def generate_questions_spacy(text_content):
    doc = nlp(text_content)
    questions = []
    for sent in doc.sents:
        if len(sent.text) < 20: continue
        nouns = [t.text for t in sent if t.pos_ in ["NOUN", "PROPN"] and len(t.text) > 3]
        if nouns:
            ans = random.choice(nouns)
            questions.append({"type": "blank", "question": sent.text.replace(ans, "_____"), "answer": ans})
    return questions

# --- Frontend ---
st.title("🎓 Smart Quiz Engine (Cloud Edition)")

if "quiz_data" not in st.session_state: st.session_state.quiz_data = []
if "score" not in st.session_state: st.session_state.score = 0

data = load_data()

# SIDEBAR
with st.sidebar:
    st.header("Settings")
    subject = st.selectbox("Subject", ["Biology", "Chemistry", "Physics"])
    mode = st.radio("Mode", ["Take Quiz", "Add New Topic", "Manage Topics"])
    st.divider()
    api_key = st.text_input("Gemini API Key", type="password")
    if api_key and st.button("Check Connection"):
        st.success("✅ Key Saved!")

# MODE: ADD TOPIC
if mode == "Add New Topic":
    st.subheader(f"Add {subject} Material")
    name = st.text_input("Topic Name")
    uploaded_file = st.file_uploader("Upload Notes", type=["pdf", "pptx"])
    text_input = st.text_area("Or Paste Text", height=150)
    
    if st.button("Generate Quiz"):
        full_text = ""
        if uploaded_file: full_text += extract_text(uploaded_file)
        if text_input: full_text += "\n" + text_input
            
        if full_text.strip():
            with st.spinner("AI is reading your notes..."):
                qs = generate_questions_gemini(full_text, api_key) if api_key else generate_questions_spacy(full_text)
                if qs:
                    data[subject][name] = qs
                    save_data(data)
                    st.success(f"Generated {len(qs)} questions!")
                else:
                    st.error("Could not generate questions.")

# MODE: TAKE QUIZ
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
                    if q['type'] in ['mcq', 'true_false']:
                        user_answers[i] = st.radio("Select:", q['options'], key=i, index=None)
                    else:
                        user_answers[i] = st.text_input("Answer:", key=i)
                    st.divider()
                if st.form_submit_button("Submit"):
                    score = 0
                    for i, q in enumerate(st.session_state.quiz_data):
                        if user_answers[i] == q['answer'] or (q['type']=='blank' and user_answers[i].lower() in q['answer'].lower()):
                            score += 1
                    st.metric("Score", f"{score}/{len(st.session_state.quiz_data)}")
    else:
        st.info("No quizzes yet. Go to 'Add New Topic' to create one!")

elif mode == "Manage Topics":
    for t in data[subject]:
        if st.button(f"Delete {t}", key=t):
            del data[subject][t]
            save_data(data)
            st.rerun()
