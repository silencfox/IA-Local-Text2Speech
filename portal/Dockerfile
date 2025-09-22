FROM nginx:stable-alpine
COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY index.html /usr/share/nginx/html/index.html
COPY script.js  /usr/share/nginx/html/script.js
COPY styles.css /usr/share/nginx/html/styles.css
EXPOSE 80
