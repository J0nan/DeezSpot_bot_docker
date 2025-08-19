FROM python:3.10.0

RUN apt-get -y update
RUN apt-get install -y ffmpeg

WORKDIR /app

COPY . /app

RUN pip install ./deezloader_lib

RUN pip install --upgrade pip
RUN pip install -r req.txt

VOLUME [ "/app/DB", "/app/logs"]

CMD [ "python", "/app/deez_bot.py"]