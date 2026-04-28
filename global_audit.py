import paramiko

def find_and_read(host, username, password):
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    try:
        client.connect(host, username=username, password=password, timeout=10)
        
        # Broad search and cat
        print("--- Global Search for DuckDNS Config ---")
        cmd = "find /etc /data /opt /srv /var/lib/docker/volumes -type f -name '*.conf' -exec grep -l 'nxchieu.duckdns.org' {} + 2>/dev/null | xargs cat"
        stdin, stdout, stderr = client.exec_command(cmd)
        print(stdout.read().decode('utf-8', 'ignore'))
        
        # Check running containers again for exact naming
        print("\n--- Docker Names Check ---")
        stdin, stdout, stderr = client.exec_command("docker ps --format '{{.Names}}'")
        print(stdout.read().decode('utf-8', 'ignore'))
        
    except Exception as e:
        print(f"Error: {str(e)}")
    finally:
        client.close()

if __name__ == "__main__":
    find_and_read("10.25.7.116", "user", "Admin@12345")
