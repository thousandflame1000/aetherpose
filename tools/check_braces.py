import sys
p='src/main.rs'
openers={'(':')','{':'}','[':']'}
closers={')':'(',']':'[','}':'{'}
stack=[]
with open(p,encoding='utf-8') as f:
    for i,line in enumerate(f,1):
        for j,ch in enumerate(line,1):
            if ch in openers:
                stack.append((ch,i,j,line.rstrip('\n')))
            elif ch in closers:
                if not stack:
                    print(f"Extra closer {ch} at {i}:{j}")
                    sys.exit(1)
                top,li,co,txt = stack.pop()
                if closers[ch] != top:
                    print(f"Mismatch: closer {ch} at {i}:{j} doesn't match opener {top} at {li}:{co}")
                    print(f"Opener line {li}: {txt}")
                    print(f"Closer line {i}: {line.rstrip()}")
                    sys.exit(1)
if stack:
    print("Unclosed openers:")
    for ch,i,j,txt in stack[-20:]:
        print(f"  opener {ch} at {i}:{j} -> {txt}")
    sys.exit(2)
print('All matched')
