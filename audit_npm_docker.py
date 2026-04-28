import paramiko

def read_npm_via_docker(host, username, password):
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    try:
        client.connect(host, username=username, password=password, timeout=10)
        
        # 1. List all proxy configuration files in NPM container
        print("--- List of Proxy Host IDs ---")
        _, so, _ = client.exec_command("docker exec npm ls /data/nginx/proxy_host/ 2>/dev/null")
        print(so.read().decode())
        
        # 2. Find which file contains the DuckDNS entry
        print("\n--- Identifying DuckDNS Proxy ID ---")
        _, so, _ = client.exec_command("docker exec npm grep -l 'nxchieu.duckdns.org' /data/nginx/proxy_host/*.conf 2>/dev/null")
        target_file = so.read().decode().strip()
        print(f"Target File: {target_file}")
        
        if target_file:
            print(f"\n--- Reading Content of {target_file} ---")
            _, so, _ = client.exec_command(f"docker exec npm cat {target_file}")
            print(so.read().decode())
            
    except Exception as e:
        print(f"Error: {str(e)}")
    finally:
        client.close()

if __name__ == "__main__":
    read_npm_via_docker("10.25.7.116", "user", "Admin@12345")
