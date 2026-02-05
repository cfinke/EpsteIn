FROM python:3.11-alpine

RUN mkdir /data

ADD ./ ./

RUN pip install -r requirements.txt

CMD ["python3", "EpsteIn.py", "--connections", "/data/Connections.csv", "--output", "/data/report.html"]
