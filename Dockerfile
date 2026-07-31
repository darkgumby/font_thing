FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .
RUN mkdir -p uploads web_outputs

EXPOSE 5000

CMD ["python3", "app.py", "--host", "0.0.0.0", "--port", "5000"]
