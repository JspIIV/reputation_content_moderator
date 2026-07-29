# { "Depends": "py-genlayer:1jb45aa8ynh2a9c9xn3b7qqh8sm5q93hwfp7jqmwsfhh8jpz09h6" }

from genlayer import *
import json

STARTING_REPUTATION = 100
MIN_REPUTATION = 0
MAX_REPUTATION = 1000

def _author_key(address) -> str:
    # Addresses reach this contract in different shapes: checksummed from
    # gl.message, lowercase from a CLI or an indexer, mixed case from a UI.
    # One canonical key stops the same person accumulating two reputations.
    return str(address).strip().lower()


REPUTATION_DELTA = {
    "APPROVED": 2,
    "WARNED": -3,
    "REMOVED": -10,
}


class ReputationContentModerator(gl.Contract):
    owner: Address
    community_rules: str
    users: TreeMap[str, str]
    posts: TreeMap[str, str]
    post_count: bigint

    def __init__(self, community_rules: str) -> None:
        self.owner = gl.message.sender_address
        self.community_rules = community_rules
        self.post_count = bigint(0)

    @gl.public.write
    def set_community_rules(self, new_rules: str) -> None:
        if gl.message.sender_address != self.owner:
            raise gl.vm.UserError("[EXPECTED] Only the contract owner may update community rules")
        self.community_rules = new_rules

    def _get_or_init_user(self, author: str) -> dict:
        author = _author_key(author)
        raw = self.users.get(author, None)
        if raw is None:
            return {
                "author": author,
                "reputation": STARTING_REPUTATION,
                "post_count": 0,
                "approved_count": 0,
                "warned_count": 0,
                "removed_count": 0,
            }
        return json.loads(raw)

    @gl.public.write
    def submit_content(self, content: str) -> None:
        author = _author_key(gl.message.sender_address.as_hex)
        community_rules = self.community_rules

        user = self._get_or_init_user(author)
        author_reputation = user["reputation"]

        def moderate() -> str:
            task = (
                "You are a content moderator for an online community. Judge the post against the\n"
                "community rules. Take the author's current reputation into account only as context\n"
                "(higher reputation does not excuse rule violations).\n\n"
                "COMMUNITY RULES:\n" + community_rules + "\n\n"
                "AUTHOR CURRENT REPUTATION: " + str(author_reputation) + "\n\n"
                "POST CONTENT:\n" + content + "\n\n"
                "Return ONLY a JSON object:\n"
                "{\"verdict\": \"APPROVED\", \"severity\": \"NONE\", \"reasoning\": \"one sentence\"}\n\n"
                "Rules:\n"
                "- verdict must be exactly APPROVED, WARNED, or REMOVED\n"
                "- APPROVED: fully complies with community rules\n"
                "- WARNED: minor or borderline violation, content stays visible\n"
                "- REMOVED: clear violation, content must be taken down\n"
                "- severity must be exactly NONE, LOW, MEDIUM, or HIGH\n"
                "- reasoning: one sentence explaining the decision\n"
                "Return ONLY the JSON, no other text."
            )
            raw = gl.nondet.exec_prompt(task)
            raw = raw.strip()
            if raw.startswith("```"):
                raw = raw.split("```")[1]
                if raw.startswith("json"):
                    raw = raw[4:]
            raw = raw.strip()
            start = raw.find("{")
            end = raw.rfind("}") + 1
            if start >= 0 and end > start:
                raw = raw[start:end]
            parsed = json.loads(raw)
            verdict = parsed.get("verdict", "WARNED")
            if verdict not in ("APPROVED", "WARNED", "REMOVED"):
                verdict = "WARNED"
            severity = parsed.get("severity", "NONE")
            if severity not in ("NONE", "LOW", "MEDIUM", "HIGH"):
                severity = "NONE"
            return json.dumps({
                "verdict": verdict,
                "severity": severity,
                "reasoning": str(parsed.get("reasoning", "")),
            })

        result_str = gl.eq_principle.prompt_comparative(
            moderate,
            principle="The verdict field must match exactly between validators.",
        )
        result = json.loads(result_str)
        verdict = result["verdict"]

        delta = REPUTATION_DELTA[verdict]
        new_reputation = max(MIN_REPUTATION, min(MAX_REPUTATION, author_reputation + delta))

        user["reputation"] = new_reputation
        user["post_count"] = int(user["post_count"]) + 1
        if verdict == "APPROVED":
            user["approved_count"] = int(user["approved_count"]) + 1
        elif verdict == "WARNED":
            user["warned_count"] = int(user["warned_count"]) + 1
        else:
            user["removed_count"] = int(user["removed_count"]) + 1
        self.users[author] = json.dumps(user)

        post_id = str(int(self.post_count))
        self.posts[post_id] = json.dumps({
            "id": post_id,
            "author": author,
            "content": content,
            "verdict": verdict,
            "severity": result["severity"],
            "reasoning": result["reasoning"],
            "reputation_before": author_reputation,
            "reputation_after": new_reputation,
        })
        self.post_count = bigint(int(self.post_count) + 1)

    @gl.public.view
    def get_community_rules(self) -> str:
        return self.community_rules

    @gl.public.view
    def get_user_reputation(self, author: str) -> str:
        author = _author_key(author)
        raw = self.users.get(author, None)
        if raw is None:
            return json.dumps({
                "author": author,
                "reputation": STARTING_REPUTATION,
                "post_count": 0,
                "approved_count": 0,
                "warned_count": 0,
                "removed_count": 0,
            })
        return raw

    @gl.public.view
    def get_post(self, post_id: str) -> str:
        data = self.posts.get(str(post_id), None)
        if data is None:
            return json.dumps({"error": "Post not found"})
        return data

    @gl.public.view
    def get_all_posts(self) -> str:
        all_posts = {}
        for i in range(int(self.post_count)):
            pid = str(i)
            all_posts[pid] = json.loads(self.posts.get(pid, "{}"))
        return json.dumps(all_posts)

    @gl.public.view
    def get_total_post_count(self) -> bigint:
        return self.post_count
