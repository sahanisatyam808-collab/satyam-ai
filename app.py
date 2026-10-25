import os

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

# Provider -> (base_url, env var for key, suggested models)
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
MAX_HISTORY = 20  # last N messages bhejte hain, taaki lamba chat na phate

st.set_page_config(page_title="Satyam", page_icon="🤝", layout="centered")
st.title("Satyam 🤝")
st.caption("Tera AI dost, jo seedha aur sahi jawab de")


if "messages" not in st.session_state:
    st.session_state.messages = []  # sirf user/assistant, system prompt bhejte waqt judta hai

# ---------- Sidebar ----------
with st.sidebar:
    st.header("Settings")
    provider = st.selectbox("Provider", list(PROVIDERS.keys()), index=0)
    base_url, key_env, models = PROVIDERS[provider]

    api_key = st.text_input(
        f"API Key ({key_env})",
        type="password",
        value=os.getenv(key_env, ""),
    )
    model = st.selectbox("Model", models, index=0)
    custom_model = st.text_input(
        "Ya apna model naam likh (optional)",
        help="Agar upar wala model band ho gaya ho toh yahan naya naam daal.",
    ).strip()
    if custom_model:
        model = custom_model

    temperature = st.slider("Temperature (mazaa)", 0.3, 1.2, 0.7, 0.05)

    if st.button("Chat clear kar"):
        st.session_state.messages = []
        st.rerun()

# ---------- History ----------
for msg in st.session_state.messages:
    with st.chat_message(msg["role"]):
        st.markdown(msg["content"])

if not api_key:
    st.warning(f"Sidebar mein API key daal pehle bhai (ya .env mein {key_env} daal).")
    st.stop()

client = OpenAI(api_key=api_key, base_url=base_url, timeout=60.0)


def stream_reply(messages):
    """Tokens yield karta hai taaki jawab dheere-dheere likhta dikhe."""
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
    st.session_state.messages.append({"role": "user", "content": prompt})
    with st.chat_message("user"):
        st.markdown(prompt)

    to_send = [{"role": "system", "content": SATYAM_SYSTEM_PROMPT}] + st.session_state.messages[-MAX_HISTORY:]

    with st.chat_message("assistant"):
        try:
            reply = st.write_stream(stream_reply(to_send))
            st.session_state.messages.append({"role": "assistant", "content": reply})
        except APIConnectionError:
            st.error("Net nahi chal raha bhai 😅 Connection check kar, phir dobara bhej.")
            st.session_state.messages.pop()
        except APITimeoutError:
            st.error("Server ne bahut der laga di. Thodi der baad try kar.")
            st.session_state.messages.pop()
        except AuthenticationError:
            st.error("API key galat hai ya expire ho gayi. Nayi key bana ke daal.")
            st.session_state.messages.pop()
        except NotFoundError:
            st.error(f"Model `{model}` nahi mila. Sidebar mein koi aur model chun ya naam check kar.")
            st.session_state.messages.pop()
        except RateLimitError:
            st.error("Limit khatam ho gayi (rate limit). Thodi der ruk ke try kar.")
            st.session_state.messages.pop()
        except Exception as e:  # koi aur gadbad
            st.error(f"Kuch gadbad ho gayi: {e}")
            st.session_state.messages.pop()
