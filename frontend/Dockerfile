FROM nginx:1.28-alpine
COPY frontend/nginx.conf /etc/nginx/nginx.conf
COPY web/ /usr/share/nginx/html/
EXPOSE 8080
USER nginx
ENTRYPOINT ["nginx"]
CMD ["-g", "daemon off;"]
