FROM node:20-alpine AS build
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci
COPY . .
ARG VITE_DEMO_VIDEO_ID=demo01
ENV VITE_DEMO_VIDEO_ID=$VITE_DEMO_VIDEO_ID
RUN npx vite build

FROM nginx:1.27-alpine
COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/dist /usr/share/nginx/html
EXPOSE 80
