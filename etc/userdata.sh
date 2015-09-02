#!/bin/bash

NGINX_CONF=$(cat <<EOF
user www-data;
worker_processes  2;

events {
    worker_connections  1024;
}


http {
    include         mime.types;
    default_type        application/octet-stream;

    sendfile        on;
    keepalive_timeout   65;

    server {
        listen     8089;
        server_name  _tsuru_nginx_admin;

        location /reload {
            content_by_lua "ngx.print(os.execute('sudo service nginx reload'))";
        }

        location /dav {
            root            /etc/nginx/sites-enabled;
            dav_methods     PUT DELETE;
            create_full_put_path    on;
            dav_access      group:rw all:r;
        }
    }

    server {
        listen 8080;
        listen 8081 ssl;

        ssl_certificate /etc/nginx/sites-enabled/dav/ssl/nginx.crt;
        ssl_certificate_key /etc/nginx/sites-enabled/dav/ssl/nginx.key;
        ssl_dhparam /etc/nginx/sites-enabled/dav/ssl/dhparams.pem;

        server_name  _tsuru_nginx_app;
        port_in_redirect off;

        location /_nginx_healthcheck/ {
            echo "WORKING";
        }

        include sites-enabled/dav/*.conf;
    }
}
EOF
)

DEBIAN_FRONTEND=noninteractive

sudo apt-get update -qq
sudo apt-get install nginx-extras -qqy
sudo mkdir -p /etc/nginx/sites-enabled/dav/ssl
sudo openssl req -x509 -nodes -days 365 -newkey rsa:2048 -keyout /etc/nginx/sites-enabled/dav/ssl/nginx.key -out /etc/nginx/sites-enabled/dav/ssl/nginx.crt -subj "/C=BR/ST=RJ/L=RJ/O=do not use me/OU=do not use me/CN=rpaas.tsuru"
sudo openssl dhparam -out /etc/nginx/sites-enabled/dav/ssl/dhparams.pem 2048
sudo chown -R www-data:www-data /etc/nginx/sites-enabled
sudo rm -f /etc/nginx/sites-enabled/default || true
echo "www-data ALL=(ALL) NOPASSWD: /usr/sbin/service nginx reload" | sudo tee -a /etc/sudoers > /dev/null
echo "$NGINX_CONF" | sudo tee /etc/nginx/nginx.conf > /dev/null
sudo /usr/sbin/service nginx restart
