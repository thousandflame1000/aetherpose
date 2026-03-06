import sys
start=int(sys.argv[1])
end=int(sys.argv[2])
with open('src/main.rs','r',encoding='utf-8') as f:
    for i,line in enumerate(f,1):
        if start<=i<=end:
            print(f"{i:5}: {line.rstrip()}")
