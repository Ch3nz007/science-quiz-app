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

@st.cache_resource
def load_nlp():
    return spacy.load("en_core_web_sm")

nlp = load_nlp()
DB_FILE = "science_topics.json"

# --- Backend Logic ---

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
    """Asks Google which models are actually available for this Key."""
    genai.configure(api_key=api_key)
    try:
        # List all models
        models = genai.list_models()
        # Find the first one that supports 'generateContent'
        for m in models:
            if 'generateContent' in m.supported_generation_methods:
                # Prefer Flash or Pro if available
                if 'flash' in m.name:
                    return m.name
                if 'pro' in m.name:
                    return m.name
        # Fallback if no specific preference found, just take the first valid one
        for m in models:
             if 'generateContent' in m.supported_generation_methods:
                 return m.name
        return None
    except Exception as e:
        return None

# --- GENERATION LOGIC ---
def generate_questions_gemini(text_content, api_key):
    # 1. Find a working model dynamically
    model_name = get_working_model_name(api_key)
    
    if not model_name:
        st.error("❌ Could not find any available Gemini models for this API Key. Check your Key permissions.")
        return []
    
    # 2. Configure and Run
    genai.configure(api_key=api_key)
    model = genai.GenerativeModel(model_name)
    
    prompt = f"""
    You are a university examiner. Generate a rigorous question bank (30-40 questions).
    
    INSTRUCTIONS:
    1. VARIATION: Test key concepts from multiple angles (Definition, True/False, Application).
    2. FORMAT: JSON Only.
    3. TYPES: "mcq", "true_false", "blank".
    
    OUTPUT JSON STRUCTURE:
    [
      {{
        "type": "mcq",
        "question": "Question text?",
        "options": ["A", "B", "C", "D"],
        "answer": "B"
      }},
      {{
        "type": "true_false",
        "question": "Statement?",
        "options": ["True", "False"],
        "answer": "False"
      }}
    ]

    NOTES:
    {text_content[:15000]} 
    """
    try:
        response = model.generate_content(prompt)
        cleaned_text = response.text.strip()
        if cleaned_text.startswith("```"):
            cleaned_text = cleaned_text.strip("`").replace("json\n", "").replace("json", "")
        return json.loads(cleaned_text)
    except Exception as e:
        st.error(f"Gemini Error ({model_name}): {e}")
        return []

def generate_questions_spacy(text_content):
    doc = nlp(text_content)
    questions = []
    all_nouns = [token.text for token in doc if token.pos_ in ["NOUN", "PROPN"] and len(token.text) > 3]
    all_nouns = list(set(all_nouns))

    for sent in doc.sents:
        sent_text = sent.text.strip().replace("\n", " ")
        if len(sent_text) < 15: continue
        target_tokens = [t for t in sent if t.pos_ in ["NOUN", "PROPN"] and len(t.text) > 3]
        if not target_tokens: continue
        target = random.choice(target_tokens)
        answer = target.text
        
        q_type = random.choice(["mcq", "blank"])
        if q_type == "blank":
            questions.append({"type": "blank", "question": sent_text.replace(answer, "______"), "answer": answer})
        elif q_type == "mcq" and len(all_nouns) >= 3:
            distractors = random.sample([n for n in all_nouns if n != answer], 3)
            options = distractors + [answer]
            random.shuffle(options)
            questions.append({"type": "mcq", "question": sent_text.replace(answer, "______"), "options": options, "answer": answer})
    return questions

# --- Frontend ---
st.title("🎓 Smart Quiz Engine (Self-Healing)")

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
    
    if api_key:
        if st.button("Check Connection"):
            model_name = get_working_model_name(api_key)
            if model_name:
                st.success(f"✅ Connected! Using model: {model_name}")
            else:
                st.error("❌ Connection failed. Key might be invalid or no models available.")

# MODE: ADD TOPIC
if mode == "Add New Topic":
    st.subheader(f"Add {subject} Material")
    name = st.text_input("Topic Name")
    uploaded_file = st.file_uploader("Upload PDF/PPTX", type=["pdf", "pptx"])
    text_input = st.text_area("Or Paste Notes", height=150)
    
    if st.button("Generate Question Bank"):
        full_text = ""
        if uploaded_file:
            extracted = extract_text(uploaded_file)
            if extracted: full_text += extracted
        if text_input:
            full_text += "\n" + text_input
            
        if not full_text.strip() or not name:
            st.error("Please provide a name and some text.")
        else:
            with st.spinner("🤖 AI is finding the best model & generating questions..."):
                if api_key:
                    qs = generate_questions_gemini(full_text, api_key)
                    method = "Gemini AI"
                else:
                    qs = generate_questions_spacy(full_text)
                    method = "Basic Logic"
                
                if qs:
                    data[subject][name] = qs
                    save_data(data)
                    st.success(f"Success! Saved {len(qs)} questions.")
                else:
                    st.error("Failed to generate questions.")

# MODE: TAKE QUIZ
elif mode == "Take Quiz":
    topics = list(data[subject].keys())
    if not topics:
        st.info("No topics found.")
    else:
        topic = st.selectbox("Choose Topic", topics)
        total_qs = len(data[subject][topic])
        num_qs = st.slider("Questions in this quiz:", 1, total_qs, min(10, total_qs))
        
        if st.button("Start Quiz"):
            dataset = data[subject][topic]
            st.session_state.quiz_data = random.sample(dataset, min(num_qs, len(dataset)))
            st.session_state.score = 0
            
        if st.session_state.quiz_data:
            with st.form("quiz_form"):
                user_answers = {}
                for i, q in enumerate(st.session_state.quiz_data):
                    st.markdown(f"**{i+1}. {q['question']}**")
                    
                    if q['type'] == 'mcq' or q['type'] == 'true_false':
                        user_answers[i] = st.radio("Select:", q['options'], key=i, index=None, label_visibility="collapsed")
                    else:
                        user_answers[i] = st.text_input("Answer:", key=i, label_visibility="collapsed")
                    st.write("") 

                submitted = st.form_submit_button("Submit Answers")
                if submitted:
                    score = 0
                    st.divider()
                    st.subheader("Results")
                    for i, q in enumerate(st.session_state.quiz_data):
                        u_ans = user_answers[i]
                        c_ans = q['answer']
                        is_correct = False
                        
                        if u_ans is None or u_ans.strip() == "":
                            is_correct = False
                        elif q['type'] == 'mcq' or q['type'] == 'true_false':
                            is_correct = (u_ans == c_ans)
                        else:
                            is_correct = (u_ans.strip().lower() in c_ans.lower())

                        if is_correct:
                            score += 1
                            st.success(f"Q{i+1}: Correct!")
                        else:
                            display_ans = u_ans if u_ans else "[No Answer]"
                            st.error(f"Q{i+1}: Incorrect.\nYour Answer: {display_ans}\nCorrect Answer: {c_ans}")
                    
                    st.metric("Final Score", f"{score} / {len(st.session_state.quiz_data)}")

# MODE: MANAGE
elif mode == "Manage Topics":
    st.subheader(f"Delete {subject} Topics")
    topics = list(data[subject].keys())
    for t in topics:
        c1, c2 = st.columns([4,1])
        c1.write(f"**{t}** ({len(data[subject][t])} qs)")
        if c2.button("Delete", key=f"del_{t}"):
            del data[subject][t]
            save_data(data)
            st.rerun()