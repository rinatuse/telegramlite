FROM python:3.9-slim

WORKDIR /app-telegram

COPY requirements.txt .

RUN pip install -r requirements.txt

COPY . .

CMD ["python", "src/test_bot.py"]

EXPOSE 80


