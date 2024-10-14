FROM python:3.11-alpine

COPY requirements.txt .
RUN pip install -r requirements.txt

COPY src/ .
COPY credentials.json .

RUN mkdir -p year2/data/

CMD ["python", "./year2/main.py"]