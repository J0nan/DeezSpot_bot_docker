FROM python:3.11-slim

RUN apt-get -y update
RUN apt-get install -y ffmpeg gcc

WORKDIR /app

COPY . /app

RUN pip install ./deezloader_lib

RUN pip install --upgrade pip
RUN pip install -r req.txt


VOLUME [ "/app/DB", "/app/credentials"]

CMD [ "python", "/app/deez_bot.py"]
