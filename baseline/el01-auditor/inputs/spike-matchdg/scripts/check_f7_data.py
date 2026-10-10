"""F7 data check: the no-flip branch must change only the flips. Compares the confirmation's generated Rotated MNIST
files with the h7 branch's: plain copies and labels byte for byte, augmented images one by one.
Writes runs/h7_no_flip/data_check.json."""
import glob, hashlib, json, os
from pathlib import Path
import torch

A = "wt-lenet-confirm/data/datasets/mnist/rot_mnist_lenet"; B = "wt-h7-noflip/data/datasets/mnist/rot_mnist_lenet"
h = lambda f: hashlib.sha256(open(f, "rb").read()).hexdigest()
fa = sorted(os.path.relpath(f, A) for f in glob.glob(A + "/*/*.pt")); fb = sorted(os.path.relpath(f, B) for f in glob.glob(B + "/*/*.pt"))
plain = [f for f in fa if f.endswith("_org_data.pt") or f.endswith("_label.pt")]
out = {"same_file_list": fa == fb, "plain_and_label_files": len(plain),
       "plain_and_label_identical": sum(h(f"{A}/{f}") == h(f"{B}/{f}") for f in plain)}
tot = fl = eq = other = 0
for f in fa:
    if not f.endswith("_data.pt") or f.endswith("_org_data.pt"): continue
    a = torch.load(f"{A}/{f}"); b = torch.load(f"{B}/{f}")
    for i in range(len(a)):
        tot += 1
        if torch.equal(a[i], b[i]): eq += 1
        elif torch.equal(a[i], torch.flip(b[i], [-1])): fl += 1
        else: other += 1
out.update({"augmented_images": tot, "unchanged": eq, "flip_only": fl, "other": other})
Path("runs/h7_no_flip/data_check.json").write_text(json.dumps(out, indent=1)); print(out)
