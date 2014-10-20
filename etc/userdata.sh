#!/bin/bash

NGINX_CONF=$(cat <<EOF
user www-data;
worker_processes  1;

events {
    worker_connections  1024;
}


http {
    include         mime.types;
    default_type        application/octet-stream;

    sendfile        on;
    keepalive_timeout   65;

    server {
        listen     80;
        server_name  _tsuru_nginx_admin;

        location /reload {
            content_by_lua "ngx.print(os.execute('sudo service nginx reload'))";
        }

        location /dav {
            allow           0.0.0.0/0;
            root            /etc/nginx/sites-enabled;
            dav_methods     PUT;
            create_full_put_path    on;
            dav_access      group:rw all:r;
        }
    }

    upstream tsuru_backend {
        192.168.50.4:80;
    }

    include sites-enabled/*;
}
EOF
)

DEBIAN_FRONTEND=noninteractive

sudo apt-get update -qq
sudo apt-get install nginx-extras -qqy
sudo mkdir -p /etc/nginx/sites-enabled
sudo chown www-data:www-data /etc/nginx/sites-enabled
echo "www-data ALL=(ALL) NOPASSWD: /usr/sbin/service nginx reload" | sudo tee -a /etc/sudoers > /dev/null
echo "$NGINX_CONF" | sudo tee /etc/nginx/nginx.conf > /dev/null
sudo /usr/sbin/service nginx restart
