FROM nginx:alpine

# Copier le fichier HTML
COPY index.html /usr/share/nginx/html/

# Copier la configuration nginx
COPY nginx.conf /etc/nginx/nginx.conf

EXPOSE 80

CMD ["nginx", "-g", "daemon off;"]