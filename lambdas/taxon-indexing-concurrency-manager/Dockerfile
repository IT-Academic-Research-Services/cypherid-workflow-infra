FROM node:16

RUN apt-get update && apt-get install -y zip

COPY package.json package-lock.json /app/

WORKDIR /app

RUN npm install

COPY app.js app.js

RUN mkdir /out

RUN zip -r /out/deployment.zip .
