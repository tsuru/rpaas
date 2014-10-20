#!/bin/bash

NGINX_CONF=$(cat <<EOF
user  www-data;
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

    include sites-enabled/*;
}
EOF
)

sudo apt-get install nginx-extras
sudo mkdir -p /etc/nginx/sites-enabled
sudo chown nodoby:nobody /etc/nginx/sites-enabled
echo "nobody ALL=(ALL) NOPASSWD: /usr/sbin/service nginx reload" | sudo tee -a /etc/sudoers
# sudo /etc/nginx/
