import paramiko
import re

def update_nginx(host, username, password):
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    try:
        client.connect(host, username=username, password=password, timeout=10)
        
        # 1. Detect the active config file
        find_cmd = "grep -l 'server_name nxchieu.duckdns.org' /etc/nginx/sites-enabled/* 2>/dev/null"
        _, so, _ = client.exec_command(find_cmd)
        fpath = so.read().decode().strip()
        
        if not fpath:
            # Try sites-available or common paths
            _, so, _ = client.exec_command("find /etc/nginx -name '*nxchieu*' 2>/dev/null")
            fpath = so.read().decode().splitlines()[0] if so.read().decode() else ""
            
        if not fpath:
            print("Error: Could not find active Nginx config file for duckdns.")
            return

        print(f"Reading active config: {fpath}")
        _, content_out, _ = client.exec_command(f"cat {fpath}")
        original_content = content_out.read().decode()
        
        # 2. Backup
        client.exec_command(f"cp {fpath} {fpath}.bak")
        
        # 3. Modify content
        new_content = original_content
        
        # Update ROOT / to /slave/
        # Matches 'location / { ... }'
        slave_loc = """    location /slave/ {
        proxy_pass http://10.25.7.111:5000/;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
    }
"""
        master_loc = """    location /master/ {
        proxy_pass http://10.25.7.142:80/;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_set_header Authorization $http_authorization;
        proxy_pass_header Authorization;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
    }
"""
        
        # Remove old ROOT location if it exists
        # We search for location / { ... } and replace it or insert before it.
        if "location / {" in new_content:
            # Simple replacement of the root block
            pattern = r"location / \{[\s\S]*?\n    \}"
            new_content = re.sub(pattern, slave_loc + "\n" + master_loc, new_content)
        else:
            # Fallback: append inside the server block
            new_content = new_content.replace("server {", "server {\n" + slave_loc + "\n" + master_loc)

        # 4. Write back
        # We'll use a temporary file then sudo mv if needed, but here assuming user has write access to config
        print("Writing new configuration...")
        with client.open_sftp().file(fpath, 'w') as f:
            f.write(new_content)
            
        # 5. Test and Reload
        print("Testing Nginx configuration...")
        _, so, se = client.exec_command("nginx -t")
        res = se.read().decode()
        print(res)
        if "syntax is ok" in res:
            print("Reloading Nginx...")
            client.exec_command("systemctl reload nginx")
            print("SUCCESS")
        else:
            print("ERROR: Nginx syntax check failed. Rolling back.")
            client.exec_command(f"cp {fpath}.bak {fpath}")
            
    except Exception as e:
        print(f"Error: {str(e)}")
    finally:
        client.close()

if __name__ == "__main__":
    update_nginx("10.25.7.116", "user", "Admin@12345")
