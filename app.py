import os
import time
import streamlit as st
from dotenv import load_dotenv
from openai import (
    APIConnectionError,
    APITimeoutError,
    AuthenticationError,
    NotFoundError,
    OpenAI,
    RateLimitError,
)

from satyam_prompt import SATYAM_SYSTEM_PROMPT

load_dotenv()

st.set_page_config(page_title="Satyam - Secure AI", page_icon="🛡️", layout="centered")

# ---------- Login Security Setup ----------
def check_password():
    def password_entered():
        if st.session_state["username"] == "satyam" and st.session_state["password"] == "baby123":
            st.session_state["password_correct"] = True
            del st.session_state["password"]
            del st.session_state["username"]
        else:
            st.session_state["password_correct"] = False

    if "password_correct" not in st.session_state:
        st.subheader("🔐 Login Required")
        st.text_input("Username", key="username")
        st.text_input("Password", type="password", key="password")
        st.button("Login", on_click=password_entered)
        return False
    elif not st.session_state["password_correct"]:
        st.subheader("🔐 Login Required")
        st.text_input("Username", key="username")
        st.text_input("Password", type="password", key="password")
        st.button("Login", on_click=password_entered)
        st.error("😕 User ID ya Password galat hai")
        return False
    else:
        return True

if not check_password():
    st.stop()

# ---------- Security & Rate Limiting ----------
if "request_timestamps" not in st.session_state:
    st.session_state.request_timestamps = []

def check_rate_limit():
    now = time.time()
    st.session_state.request_timestamps = [t for t in st.session_state.request_timestamps if now - t < 60]
    if len(st.session_state.request_timestamps) >= 15:
        return False
    st.session_state.request_timestamps.append(now)
    return True

def sanitize_input(text):
    if not isinstance(text, str):
        return ""
    return text.strip()

PROVIDERS = {
    "Groq": (
        "https://api.groq.com/openai/v1",
        "GROQ_API_KEY",
        ["llama-3.3-70b-versatile", "llama-3.1-8b-instant"],
    ),
    "OpenRouter": (
        "https://openrouter.ai/api/v1",
        "OPENROUTER_API_KEY",
        ["meta-llama/llama-3.3-70b-instruct"],
    ),
    "Together": (
        "https://api.together.xyz/v1",
        "TOGETHER_API_KEY",
        ["meta-llama/Llama-3.3-70B-Instruct-Turbo"],
    ),
}
MAX_HISTORY = 20

st.title("Satyam 🛡️ (Secure & Protected)")
st.caption("Tera powerful aur secure AI dost")

if "messages" not in st.session_state:
    st.session_state.messages = []

# ---------- Sidebar ----------
with st.sidebar:
    st.header("Security & Settings")
    provider = st.selectbox("Provider", list(PROVIDERS.keys()), index=0)
    base_url, key_env, models = PROVIDERS[provider]

    default_key = ""
    try:
        if key_env in st.secrets:
            default_key = st.secrets[key_env]
    except Exception:
        pass
    if not default_key:
        default_key = os.getenv(key_env, "")

    api_key = st.text_input(
        f"API Key ({key_env})",
        type="password",
        value=default_key,
    )
    model = st.selectbox("Model", models, index=0)
    custom_model = st.text_input(
        "Ya apna model naam likh (optional)",
    ).strip()
    if custom_model:
        model = sanitize_input(custom_model)

    temperature = st.slider("Temperature (mazaa)", 0.3, 1.2, 0.7, 0.05)

    if st.button("Chat clear kar"):
        st.session_state.messages = []
        st.rerun()

# ---------- History ----------
for msg in st.session_state.messages:
    with st.chat_message(msg["role"]):
        st.markdown(msg["content"])

if not api_key:
    st.warning(f"Pehle apni API key daal sidebar mein ya secrets mein ({key_env}).")
    st.stop()

client = OpenAI(api_key=api_key, base_url=base_url, timeout=60.0)

def stream_reply(messages):
    stream = client.chat.completions.create(
        model=model,
        messages=messages,
        temperature=temperature,
        max_tokens=1024,
        stream=True,
    )
    for chunk in stream:
        if chunk.choices and chunk.choices[0].delta.content:
            yield chunk.choices[0].delta.content

# ---------- Chat ----------
if prompt := st.chat_input("Satyam se baat kar..."):
    clean_prompt = sanitize_input(prompt)
    if not clean_prompt:
        st.warning("Khaali message nahi bhej sakte!")
    elif not check_rate_limit():
        st.error("Thoda aaram se! Bahut jaldi message bhej raha hai.")
    else:
        st.session_state.messages.append({"role": "user", "content": clean_prompt})
        with st.chat_message("user"):
            st.markdown(clean_prompt)

        to_send = [{"role": "system", "content": SATYAM_SYSTEM_PROMPT}] + st.session_state.messages[-MAX_HISTORY:]

        with st.chat_message("assistant"):
            try:
                reply = st.write_stream(stream_reply(to_send))
                st.session_state.messages.append({"role": "assistant", "content": reply})
            except APIConnectionError:
                st.error("Net nahi chal raha 😅 Connection check kar.")
                st.session_state.messages.pop()
            except APITimeoutError:
                st.error("Server ne bahut der laga di.")
                st.session_state.messages.pop()
            except AuthenticationError:
                st.error("API key galat hai ya expire ho gayi.")
                st.session_state.messages.pop()
            except NotFoundError:
                st.error(f"Model `{model}` nahi mila.")
                st.session_state.messages.pop()
            except RateLimitError:
                st.error("API provider ki limit khatam ho gayi.")
                st.session_state.messages.pop()
            except Exception as e:
                st.error(f"Kuch technical gadbad ho gayi: {e}")
                st.session_state.messages.pop()
                
