"""Быстрый путь: Streamlit-прототип на том же слое llm.py.

Когда использовать: задача про анализ/обработку данных или контента, и UI
вторичен. Собирается за 30-40 минут вместо двух часов.
Когда НЕ использовать: решение продают глазами (креатив, дизайн, медиа) —
тогда берите app/main.py + web/index.html.

Запуск:  pip install streamlit && streamlit run app_fast.py
"""
import streamlit as st

from app import config, db, llm

st.set_page_config(page_title=config.APP_NAME, layout="wide")
db.init()

st.title(config.APP_NAME)
if config.DEMO_MODE:
    st.info("DEMO MODE: ключ не задан, ответы — заглушки. Задайте OPENAI_API_KEY в .env.")

with st.sidebar:
    st.header("Параметры")
    system = st.text_area("Системный промпт", "Ты — полезный ассистент. Отвечай кратко.")
    st.divider()
    st.caption("Статистика")
    st.json(db.stats())

prompt = st.text_area("Запрос", height=120, placeholder="Опишите, что нужно сгенерировать…")

col1, col2 = st.columns([1, 4])
if col1.button("Сгенерировать", type="primary", use_container_width=True):
    if prompt.strip():
        with st.spinner("Думаю…"):
            result = llm.complete(prompt, system)
        st.markdown("### Результат")
        st.write(result)
        if st.button("Сохранить"):
            db.add_item(prompt[:80], {"prompt": prompt, "result": result})
            st.success("Сохранено")

st.divider()
st.subheader("Сохранённые результаты")
items = db.list_items(20)
if items:
    st.dataframe(
        [{"id": i["id"], "title": i["title"], "created": i["created_at"]} for i in items],
        use_container_width=True,
    )
else:
    st.caption("Пока пусто.")
