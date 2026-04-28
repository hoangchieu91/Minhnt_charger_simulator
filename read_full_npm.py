import paramiko

def read_full_npm_conf(host, username, password):
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    try:
        client.connect(host, username=username, password=password, timeout=10)
        
        target_file = "/var/lib/docker/volumes/traefik-proxy_npm-data/_data/nginx/proxy_host/8.conf"
        print(f"--- Reading Full Content of {target_file} ---")
        _, so, _ = client.exec_command(f"cat {target_file}")
        print(so.read().decode())
        
        # Also check NPM DB if possible (SQLite)
        db_file = "/var/lib/docker/volumes/traefik-proxy_npm-data/_data/database.sqlite"
        print(f"\n--- NPM Database Check ---")
        _, so, _ = client.exec_command(f"ls -l {db_file}")
        print(so.read().decode())
        
        # Check if there are other hosts
        print("\n--- List of all Proxy Hosts ---")
        _, so, _ = client.exec_command("ls /var/lib/docker/volumes/traefik-proxy_npm-data/_data/nginx/proxy_host/*.conf")
        print(so.read().decode())
        
    except Exception as e:
        print(f"Error: {str(e)}")
    finally:
        client.close()

if __name__ == "__main__":
    read_full_npm_conf("10.25.7.116", "user", "Admin@12345")
