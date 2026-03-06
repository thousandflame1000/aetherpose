p='src/main.rs'
openers={'(':')','{':'}','[':']'}
closers={')':'(',']':'[','}':'{'}
stack=[]
mismatches=[]
with open(p,encoding='utf-8') as f:
    for i,line in enumerate(f,1):
        for j,ch in enumerate(line,1):
            if ch in openers:
                stack.append((ch,i,j,line.rstrip('\n')))
            elif ch in closers:
                if not stack:
                    mismatches.append((f"Extra closer {ch}",i,j,line.rstrip()))
                else:
                    top,li,co,txt = stack.pop()
                    if closers[ch] != top:
                        mismatches.append((f"Mismatch: closer {ch} at {i}:{j} doesn't match opener {top} at {li}:{co}",li,co,txt,i,j,line.rstrip()))
# report
if mismatches:
    print('Mismatches found:')
    for m in mismatches:
        print(m)
if stack:
    print('\nUnclosed openers stack (bottom->top):')
    for ch,i,j,txt in stack:
        print(f"{ch} at {i}:{j} -> {txt}")
else:
    print('No unclosed openers')
