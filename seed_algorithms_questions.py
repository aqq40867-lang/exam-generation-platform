"""
One-time seed script: inserts a complete sample "Algorithms and Data
Structures" exam paper (5 questions, 100 marks total -- matching a 2-hour
exam, same scope/difficulty as the reference Loughborough sample paper)
directly into the question bank, under a chosen teacher account.

Usage:
    python seed_algorithms_questions.py [username]

If [username] is omitted, defaults to "Yan". The module code used is
"25COP923" (matching the reference paper); it's automatically added to
that teacher's assigned modules if it isn't already there, so it shows up
correctly in the Module dropdown on the create/edit question pages
afterwards.

Coverage (mirrors the reference paper's structure, original questions):
  1. Definitions                       10 marks
  2. Algorithm Analysis (binary search) 15 marks
  3. Data Structures (linked-list queue) 20 marks
  4. Graphs (Dijkstra shortest paths)   35 marks
  5. Minimum Spanning Trees (Kruskal's)  20 marks
                                       ----------
                                       100 marks
"""

import sys
from datetime import datetime

from database import (
    add_question,
    replace_question_parts,
    get_teacher_modules,
    set_teacher_modules,
    get_user_by_username,
)

MODULE = "25COP923"

QUESTIONS = [
    {
        "title": "Definitions",
        "main_question": "Provide informal definitions of the concepts below.",
        "parts": [
            {
                "Description": "What is a hash table? Explain how it achieves fast lookup on average.",
                "Marks": 5,
                "Answer": (
                    "A hash table maps keys to values using a hash function that computes an index "
                    "into an array of buckets. On average, lookup, insertion and deletion run in O(1) "
                    "time because the hash function spreads keys roughly uniformly across buckets. "
                    "Collisions (two keys hashing to the same bucket) are handled via chaining or open "
                    "addressing."
                ),
                "Answer space": "half",
            },
            {
                "Description": (
                    "What is a greedy algorithm? State one property that must hold for a greedy "
                    "approach to guarantee an optimal solution."
                ),
                "Marks": 5,
                "Answer": (
                    "A greedy algorithm builds a solution step by step, always choosing the option that "
                    "looks best by some local criterion, without reconsidering earlier choices. A greedy "
                    "approach guarantees optimality when the problem has the greedy-choice property (a "
                    "locally optimal choice leads to a globally optimal solution) together with optimal "
                    "substructure (an optimal solution contains optimal solutions to its subproblems)."
                ),
                "Answer space": "half",
            },
        ],
    },
    {
        "title": "Algorithm Analysis",
        "main_question": (
            "What is the worst-case time complexity of the following algorithm in big-O notation? "
            "What task is performed by the algorithm? How is that task achieved? (Answer each in the "
            "corresponding sub-question.)\n\n"
            "Procedure(A, n, target)\n"
            "1  low <- 1, high <- n\n"
            "2  while low <= high do\n"
            "3      mid <- floor((low + high) / 2)\n"
            "4      if A[mid] = target then\n"
            "5          return mid\n"
            "6      else if A[mid] < target then\n"
            "7          low <- mid + 1\n"
            "8      else\n"
            "9          high <- mid - 1\n"
            "10 return -1"
        ),
        "parts": [
            {"Description": "Complexity?", "Marks": 5, "Answer": "O(log n)", "Answer space": "half"},
            {
                "Description": "Task performed?",
                "Marks": 5,
                "Answer": (
                    "Binary search: find the index of `target` within a sorted array A, returning -1 "
                    "if it isn't present."
                ),
                "Answer space": "half",
            },
            {
                "Description": "How achieved?",
                "Marks": 5,
                "Answer": (
                    "The algorithm repeatedly halves the search range: it compares the middle element "
                    "to the target and discards the half of the range that cannot contain it, "
                    "continuing until the target is found or the range is empty. Because the search "
                    "space halves each iteration, at most O(log n) comparisons are needed."
                ),
                "Answer space": "half",
            },
        ],
    },
    {
        "title": "Data Structures",
        "main_question": (
            "Consider a queue (FIFO) implemented as a singly linked list with head (front) and tail "
            "(back) pointers, where enqueue adds to the tail and dequeue removes from the head."
        ),
        "parts": [
            {
                "Description": (
                    "Starting from an empty queue, perform the operations: enqueue(3), enqueue(7), "
                    "enqueue(1), dequeue(), enqueue(9), dequeue(). State the final contents of the "
                    "queue (front to back) and the value returned by each dequeue call."
                ),
                "Marks": 8,
                "Answer": (
                    "After enqueue(3), enqueue(7), enqueue(1): [3,7,1]. The first dequeue() removes and "
                    "returns 3, leaving [7,1]. enqueue(9) gives [7,1,9]. The second dequeue() removes "
                    "and returns 7, leaving [1,9]. Final queue (front to back): [1, 9]. The dequeue "
                    "calls returned 3, then 7."
                ),
                "Answer space": "half",
            },
            {
                "Description": (
                    "Suppose each node has fields `value` and `next`, and the queue object Q tracks "
                    "`head` and `tail`. Write pseudocode for Enqueue(Q, value)."
                ),
                "Marks": 6,
                "Answer": (
                    "Enqueue(Q, value)\n"
                    "1  node <- new Node(value, next = NIL)\n"
                    "2  if Q.head = NIL then\n"
                    "3      Q.head <- node\n"
                    "4      Q.tail <- node\n"
                    "5  else\n"
                    "6      Q.tail.next <- node\n"
                    "7      Q.tail <- node"
                ),
                "Answer space": "half",
            },
            {
                "Description": (
                    "Write pseudocode for Dequeue(Q), which removes and returns the value at the front "
                    "of the queue."
                ),
                "Marks": 6,
                "Answer": (
                    "Dequeue(Q)\n"
                    "1  if Q.head = NIL then\n"
                    "2      error \"queue is empty\"\n"
                    "3  value <- Q.head.value\n"
                    "4  Q.head <- Q.head.next\n"
                    "5  if Q.head = NIL then\n"
                    "6      Q.tail <- NIL\n"
                    "7  return value"
                ),
                "Answer space": "half",
            },
        ],
    },
    {
        "title": "Graphs",
        "main_question": (
            "An emergency response coordinator manages a network of towns connected by roads. Each "
            "road has an associated travel time. In the event of a flood, the coordinator needs to "
            "know the minimum time required to send aid from the central depot town to every other "
            "town in the network."
        ),
        "parts": [
            {
                "Description": "Explain how this problem can be modelled as a graph problem.",
                "Marks": 10,
                "Answer": (
                    "Model the road network as a weighted graph: each town is a vertex, each road is an "
                    "edge (undirected, since roads can be travelled in either direction), and each "
                    "edge's weight is the travel time along that road. Finding the minimum time to "
                    "reach every town from the depot is equivalent to computing single-source "
                    "shortest-path distances from the depot vertex to every other vertex."
                ),
                "Answer space": "half",
            },
            {
                "Description": (
                    "Design an algorithm that computes these minimum travel times. Describe it in "
                    "words, give high-level pseudocode, and state which known algorithm it is based on."
                ),
                "Marks": 15,
                "Answer": (
                    "We use Dijkstra's algorithm for single-source shortest paths with non-negative "
                    "edge weights.\n\n"
                    "ShortestTimes(G = (V, E), depot)\n"
                    "1  for each v in V do dist[v] <- infinity\n"
                    "2  dist[depot] <- 0\n"
                    "3  PQ <- priority queue containing (depot, 0)\n"
                    "4  while PQ not empty do\n"
                    "5      u <- PQ.extractMin()\n"
                    "6      for each neighbour w of u with edge weight t do\n"
                    "7          if dist[u] + t < dist[w] then\n"
                    "8              dist[w] <- dist[u] + t\n"
                    "9              PQ.insertOrDecreaseKey(w, dist[w])\n"
                    "10 return dist"
                ),
                "Answer space": "full",
            },
            {
                "Description": (
                    "Discuss a suitable representation of the graph and an implementation of your "
                    "algorithm. Mention any auxiliary data structures and estimate the running time."
                ),
                "Marks": 10,
                "Answer": (
                    "An adjacency list (a list of outgoing edges and weights per vertex) is efficient "
                    "here, together with a dist[] array and a min-heap priority queue for selecting the "
                    "next closest vertex. With an adjacency list and a binary heap, Dijkstra's "
                    "algorithm runs in O((|V| + |E|) log |V|) time."
                ),
                "Answer space": "half",
            },
        ],
    },
    {
        "title": "Minimum Spanning Trees",
        "main_question": "Let G = (V, E) be a connected, weighted, undirected graph.",
        "parts": [
            {
                "Description": (
                    "Define what a spanning tree of G is, and what a minimum spanning tree (MST) of G "
                    "is."
                ),
                "Marks": 5,
                "Answer": (
                    "A spanning tree of G is a subgraph that contains all of G's vertices, is "
                    "connected, and contains no cycles (a tree). A minimum spanning tree is a spanning "
                    "tree whose total edge weight is the smallest among all possible spanning trees of "
                    "G."
                ),
                "Answer space": "half",
            },
            {
                "Description": "State the problem solved by Kruskal's algorithm, giving its input and output.",
                "Marks": 5,
                "Answer": (
                    "Kruskal's algorithm solves the minimum spanning tree problem for a connected, "
                    "weighted, undirected graph. Input: a connected undirected graph G = (V, E) with "
                    "edge weights. Output: a minimum spanning tree of G."
                ),
                "Answer space": "half",
            },
            {
                "Description": (
                    "Run the simple (non-optimised) version of Kruskal's algorithm on the graph with "
                    "vertices {P, Q, R, S, T} and edges P-Q (3), P-R (1), Q-R (4), Q-S (6), R-S (2), "
                    "R-T (5), S-T (3). List the edges in sorted order, state for each whether it is "
                    "taken, and give the total weight of the resulting minimum spanning tree."
                ),
                "Marks": 10,
                "Answer": (
                    "Sorted edges: P-R (1), R-S (2), P-Q (3), S-T (3), Q-R (4), R-T (5), Q-S (6).\n"
                    "P-R (1): no cycle, taken. MST = {P-R}\n"
                    "R-S (2): no cycle, taken. MST = {P-R, R-S}\n"
                    "P-Q (3): no cycle, taken. MST = {P-R, R-S, P-Q}\n"
                    "S-T (3): no cycle, taken. MST = {P-R, R-S, P-Q, S-T}\n"
                    "Q-R (4): would create a cycle (P-Q-R-P), rejected.\n"
                    "R-T (5): R and T are already connected via R-S-T, rejected.\n"
                    "Q-S (6): already connected, rejected.\n"
                    "5 vertices need 4 edges for a spanning tree, already reached after S-T, so all "
                    "remaining edges are rejected. Total MST weight = 1 + 2 + 3 + 3 = 9."
                ),
                "Answer space": "full",
            },
        ],
    },
]


def main():
    username = sys.argv[1] if len(sys.argv) > 1 else "Yan"

    if not get_user_by_username(username):
        print(f"No user named '{username}' found. Aborting -- pass an existing username as an argument.")
        sys.exit(1)

    # Make sure the module shows up in this teacher's Module dropdown
    # afterwards (merges with whatever they're already assigned).
    assigned = get_teacher_modules(username)
    if MODULE not in assigned:
        set_teacher_modules(username, assigned + [MODULE])
        print(f"Assigned module {MODULE} to '{username}'.")

    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    total_marks = 0

    for q in QUESTIONS:
        marks = sum(p["Marks"] for p in q["parts"])
        qid = add_question({
            "Question": q["title"],
            "Main question": q["main_question"],
            "Marks": marks,
            "Answer": None,
            "Status": "Draft",
            "Version": 1,
            "Created by": username,
            "Created at": now,
            "Usage": 0,
            "Module": MODULE,
        })
        replace_question_parts(qid, q["parts"])
        total_marks += marks
        print(f"Created question #{qid}: {q['title']} ({marks} marks, {len(q['parts'])} sub-question(s))")

    print(f"\nDone. {len(QUESTIONS)} questions created under '{username}', module {MODULE}.")
    print(f"Total marks: {total_marks} (matches a 2-hour exam paper).")
    print("Go to /exams/export to select all 5 and generate the full paper.")


if __name__ == "__main__":
    main()
