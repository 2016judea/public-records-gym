"""Ask a Claude model every candidate WITHOUT tools. A task it answers from memory
(or by lucky guess) is worthless as tool-use RL data, so it is dropped.

Uses `claude -p` (Aidan's subscription, no API key). Writes no_tool_reward on each
candidate in place.
"""
import concurrent.futures as cf
import json
import subprocess
import sys

from gym import grader

SYS = ("You answer questions about Minnesota public records. You have no tools. "
       "Give your single best answer even if unsure. Reply with ONLY the answer: a number, an ID, "
       "or a JSON list, nothing else.")
MODEL = "sonnet"


def ask(prompt):
    r = subprocess.run(["claude", "-p", "--model", MODEL, "--tools", "", "--system-prompt", SYS,
                        "--output-format", "json", prompt],
                       capture_output=True, text=True, timeout=300, cwd="/private/tmp")
    try:
        return json.loads(r.stdout).get("result", "").strip()
    except ValueError:
        return None


def main(path="answer_keys/candidates.jsonl"):
    tasks = [json.loads(l) for l in open(path)]
    with cf.ThreadPoolExecutor(6) as ex:
        answers = list(ex.map(lambda t: ask(t["prompt"]), tasks))
    for t, a in zip(tasks, answers):
        g = grader.grade(t["grader"], t["answer"], a)
        t["no_tool_answer"], t["no_tool_reward"], t["no_tool_model"] = a, g["reward"], f"claude-{MODEL}"
    with open(path, "w") as f:
        for t in tasks:
            f.write(json.dumps(t) + "\n")
    solved = [t["id"] for t in tasks if t["no_tool_reward"] > 0]
    print(f"no-tool: {len(solved)}/{len(tasks)} got any reward without tools: {solved}")


if __name__ == "__main__":
    main(*sys.argv[1:])
