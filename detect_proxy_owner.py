import paramiko

def detect_proxy_owner(host, username, password):
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    try:
        client.connect(host, username=username, password=password, timeout=10)
        
        # 1. Check open ports and owning process/container
        print("--- Port 80 Ownership ---")
        _, so, _ = client.exec_command("docker ps --format '{{.Names}}\t{{.Ports}}' | grep ':80->80'")
        print(so.read().decode())
        
        # 2. Search for the DuckDNS entry globally but excluding common noises
        print("\n--- Searching for 'nxchieu.duckdns.org' Config ---")
        search_cmd = "find /etc /opt /home /data /var/lib/docker/volumes -type f -name '*.conf' -exec grep -l 'nxchieu.duckdns.org' {} + 2>/dev/null"
        _, so, _ = client.exec_command(search_cmd)
        results = so.read().decode()
        print(results)
        
        for f in results.splitlines():
            print(f"\n--- Reading {f} ---")
            _, so, _ = client.exec_command(f"cat {f}")
            print(so.read().decode())
            
    except Exception as e:
        print(f"Error: {str(e)}")
    finally:
        client.close()

if __name__ == "__main__":
    detect_proxy_owner("10.25.7.116", "user", "Admin@12345")
