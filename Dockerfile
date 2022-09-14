FROM python:alpine

WORKDIR /app

COPY req.txt req.txt

RUN pip install --upgrade pip
RUN pip install -r req.txt

COPY . /app

CMD [ "python", "/app/deez_bot.py"]