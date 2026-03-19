FROM python:3.10

RUN apt-get -y update
RUN apt-get install -y ffmpeg git

WORKDIR /app

COPY . /app

RUN pip install --upgrade pip
RUN pip install -r req.txt
RUN pip install ./deezloader_lib

VOLUME [ "/app/DB", "/app/logs", "/app/credentials"]

CMD [ "python", "/app/deez_bot.py"]