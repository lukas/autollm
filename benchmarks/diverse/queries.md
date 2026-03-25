# Diverse Benchmark Queries (500 total)

This file contains all queries used in the `diverse` benchmark preset.

## Category breakdown

- **Short Factual**: 55 queries
- **Coding**: 80 queries
- **Creative Writing**: 51 queries
- **Math Reasoning**: 50 queries
- **Science Tech**: 41 queries
- **Analysis Opinion**: 42 queries
- **Instruction Howto**: 41 queries
- **Summarization**: 17 queries
- **Translation Language**: 31 queries
- **Conversation Roleplay**: 31 queries
- **Domain Specific**: 31 queries
- **Long Form Complex**: 30 queries

---

## Short Factual (55 queries)

### 1. What is the capital of Mongolia?

What is the capital of Mongolia?

### 2. How many bones are in the human body?

How many bones are in the human body?

### 3. What year did the Berlin Wall fall?

What year did the Berlin Wall fall?

### 4. Who wrote 'One Hundred Years of Solitude'?

Who wrote 'One Hundred Years of Solitude'?

### 5. What is the chemical formula for table salt?

What is the chemical formula for table salt?

### 6. What is the speed of light in meters per second?

What is the speed of light in meters per second?

### 7. Name the largest ocean on Earth.

Name the largest ocean on Earth.

### 8. What programming language was created by Guido van Rossum?

What programming language was created by Guido van Rossum?

### 9. What is the boiling point of water at sea level in Celsius?

What is the boiling point of water at sea level in Celsius?

### 10. Who painted the Mona Lisa?

Who painted the Mona Lisa?

### 11. What is the smallest prime number?

What is the smallest prime number?

### 12. How many chromosomes do humans have?

How many chromosomes do humans have?

### 13. What does DNA stand for?

What does DNA stand for?

### 14. What is the currency of Japan?

What is the currency of Japan?

### 15. Who discovered penicillin?

Who discovered penicillin?

### 16. What is the atomic number of carbon?

What is the atomic number of carbon?

### 17. What planet is known as the Red Planet?

What planet is known as the Red Planet?

### 18. How many continents are there?

How many continents are there?

### 19. What is the longest river in Africa?

What is the longest river in Africa?

### 20. Who invented the telephone?

Who invented the telephone?

### 21. What does HTTP stand for?

What does HTTP stand for?

### 22. What is the largest mammal?

What is the largest mammal?

### 23. In what year was the first iPhone released?

In what year was the first iPhone released?

### 24. What is the square root of 144?

What is the square root of 144?

### 25. Who was the first person to walk on the Moon?

Who was the first person to walk on the Moon?

### 26. What gas do plants absorb from the atmosphere?

What gas do plants absorb from the atmosphere?

### 27. What is the capital of Australia?

What is the capital of Australia?

### 28. How many sides does a hexagon have?

How many sides does a hexagon have?

### 29. What is the tallest mountain in the world?

What is the tallest mountain in the world?

### 30. Who wrote the theory of relativity?

Who wrote the theory of relativity?

### 31. What is the freezing point of water in Fahrenheit?

What is the freezing point of water in Fahrenheit?

### 32. Name the four fundamental forces of nature.

Name the four fundamental forces of nature.

### 33. What is the most abundant element in the universe?

What is the most abundant element in the universe?

### 34. What language has the most native speakers worldwide?

What language has the most native speakers worldwide?

### 35. How many bytes are in a kilobyte?

How many bytes are in a kilobyte?

### 36. What organ pumps blood through the human body?

What organ pumps blood through the human body?

### 37. What year did World War II end?

What year did World War II end?

### 38. What is the chemical symbol for gold?

What is the chemical symbol for gold?

### 39. How many planets are in our solar system?

How many planets are in our solar system?

### 40. What is the largest desert in the world?

What is the largest desert in the world?

### 41. Who developed the polio vaccine?

Who developed the polio vaccine?

### 42. What is the main ingredient in glass?

What is the main ingredient in glass?

### 43. What does GPU stand for?

What does GPU stand for?

### 44. What is the most spoken language in South America?

What is the most spoken language in South America?

### 45. Name the three states of matter.

Name the three states of matter.

### 46. What is the distance from the Earth to the Moon in kilometers?

What is the distance from the Earth to the Moon in kilometers?

### 47. Who wrote 'The Art of War'?

Who wrote 'The Art of War'?

### 48. What is the pH of pure water?

What is the pH of pure water?

### 49. How many teeth does an adult human typically have?

How many teeth does an adult human typically have?

### 50. What is the national animal of Scotland?

What is the national animal of Scotland?

### 51. What is the Pythagorean theorem?

What is the Pythagorean theorem?

### 52. Who is the current Secretary-General of the United Nations?

Who is the current Secretary-General of the United Nations?

### 53. What is the largest organ in the human body?

What is the largest organ in the human body?

### 54. What does SQL stand for?

What does SQL stand for?

### 55. What is the hardest natural substance on Earth?

What is the hardest natural substance on Earth?

## Coding (80 queries)

### 1. Write a Python function that checks whether a given string is a palindrome.

Write a Python function that checks whether a given string is a palindrome.

### 2. Implement a binary search algorithm in Python that works on a sorted list of integers.

Implement a binary search algorithm in Python that works on a sorted list of integers.

### 3. Write a SQL query to find the top 5 customers by total order amount from tables `customers` and `ord...

Write a SQL query to find the top 5 customers by total order amount from tables `customers` and `orders`.

### 4. Explain the difference between `let`, `const`, and `var` in JavaScript with examples.

Explain the difference between `let`, `const`, and `var` in JavaScript with examples.

### 5. Write a Rust function that finds the nth Fibonacci number using memoization.

Write a Rust function that finds the nth Fibonacci number using memoization.

### 6. Create a bash one-liner that finds all Python files modified in the last 24 hours and counts their t...

Create a bash one-liner that finds all Python files modified in the last 24 hours and counts their total lines.

### 7. Write a Python decorator that caches function results with a TTL (time-to-live) expiration.

Write a Python decorator that caches function results with a TTL (time-to-live) expiration.

### 8. Implement a simple linked list in C with insert, delete, and print operations.

Implement a simple linked list in C with insert, delete, and print operations.

### 9. Write a JavaScript async function that fetches data from an API with retry logic (max 3 attempts, ex...

Write a JavaScript async function that fetches data from an API with retry logic (max 3 attempts, exponential backoff).

### 10. Given this Python code, identify the bug and fix it:

Given this Python code, identify the bug and fix it:

```python
def merge_sorted(a, b):
    result = []
    i = j = 0
    while i < len(a) and j < len(b):
        if a[i] <= b[j]:
            result.append(a[i])
            i += 1
        else:
            result.append(b[j])
            j += 1
    return result
```

### 11. Write a SQL window function query that calculates a running total of sales by month.

Write a SQL window function query that calculates a running total of sales by month.

### 12. Implement a thread-safe singleton pattern in Python.

Implement a thread-safe singleton pattern in Python.

### 13. Write a TypeScript generic function that deeply merges two objects.

Write a TypeScript generic function that deeply merges two objects.

### 14. Create a Python context manager that times the execution of a code block and logs it.

Create a Python context manager that times the execution of a code block and logs it.

### 15. Write a regular expression that validates email addresses, then explain each part.

Write a regular expression that validates email addresses, then explain each part.

### 16. Implement quicksort in Python without using extra space (in-place).

Implement quicksort in Python without using extra space (in-place).

### 17. Write a Go function that reads a CSV file and returns a slice of maps.

Write a Go function that reads a CSV file and returns a slice of maps.

### 18. Create a React component in TypeScript that implements an infinite scroll list with virtualization.

Create a React component in TypeScript that implements an infinite scroll list with virtualization.

### 19. Write a Python function that converts a nested dictionary to a flat dictionary with dot-notation key...

Write a Python function that converts a nested dictionary to a flat dictionary with dot-notation keys.

### 20. Explain how Python's garbage collector works, including reference counting and the generational GC.

Explain how Python's garbage collector works, including reference counting and the generational GC.

### 21. Write a SQL query that finds duplicate rows in a table based on multiple columns.

Write a SQL query that finds duplicate rows in a table based on multiple columns.

### 22. Implement a simple LRU cache in Python using only built-in data structures.

Implement a simple LRU cache in Python using only built-in data structures.

### 23. Write a bash script that monitors a log file for errors and sends an alert (print to stdout) when a ...

Write a bash script that monitors a log file for errors and sends an alert (print to stdout) when a new error appears.

### 24. Create a Python dataclass that validates its fields on initialization (e.g., age must be positive, e...

Create a Python dataclass that validates its fields on initialization (e.g., age must be positive, email must contain @).

### 25. Write a JavaScript function that deep-clones an object, handling circular references.

Write a JavaScript function that deep-clones an object, handling circular references.

### 26. Implement a trie (prefix tree) in Python with insert, search, and startsWith methods.

Implement a trie (prefix tree) in Python with insert, search, and startsWith methods.

### 27. Write a Dockerfile for a Python Flask app that uses multi-stage builds to minimize image size.

Write a Dockerfile for a Python Flask app that uses multi-stage builds to minimize image size.

### 28. Review this code and suggest improvements:

Review this code and suggest improvements:

```python
def process_data(data):
    results = []
    for i in range(len(data)):
        if data[i] != None:
            try:
                val = int(data[i])
                if val > 0:
                    results.append(val * 2)
            except:
                pass
    return results
```

### 29. Write a Python function that generates all permutations of a string without using itertools.

Write a Python function that generates all permutations of a string without using itertools.

### 30. Create a GitHub Actions workflow YAML that runs tests, lints, and deploys on push to main.

Create a GitHub Actions workflow YAML that runs tests, lints, and deploys on push to main.

### 31. Implement a rate limiter using the token bucket algorithm in Python.

Implement a rate limiter using the token bucket algorithm in Python.

### 32. Write a SQL query to find the second highest salary in each department.

Write a SQL query to find the second highest salary in each department.

### 33. Create a Python generator that reads a large file line by line and yields parsed JSON objects.

Create a Python generator that reads a large file line by line and yields parsed JSON objects.

### 34. Write a JavaScript Proxy handler that logs all property access and modifications on an object.

Write a JavaScript Proxy handler that logs all property access and modifications on an object.

### 35. Implement the observer pattern in Python with type hints.

Implement the observer pattern in Python with type hints.

### 36. Write a Python function that detects cycles in a directed graph using DFS.

Write a Python function that detects cycles in a directed graph using DFS.

### 37. Create a Makefile with targets for build, test, lint, and clean for a Python project.

Create a Makefile with targets for build, test, lint, and clean for a Python project.

### 38. Write a Python script using asyncio that makes 100 concurrent HTTP requests and collects results.

Write a Python script using asyncio that makes 100 concurrent HTTP requests and collects results.

### 39. Implement a simple expression parser that evaluates arithmetic expressions like '3 + 4 * (2 - 1)' in...

Implement a simple expression parser that evaluates arithmetic expressions like '3 + 4 * (2 - 1)' in Python.

### 40. Write a PostgreSQL function that generates a UUID and handles conflicts on insert (upsert).

Write a PostgreSQL function that generates a UUID and handles conflicts on insert (upsert).

### 41. Create a Python class that implements the iterator protocol for a binary tree (in-order traversal).

Create a Python class that implements the iterator protocol for a binary tree (in-order traversal).

### 42. Write unit tests using pytest for a function that calculates compound interest. Cover edge cases.

Write unit tests using pytest for a function that calculates compound interest. Cover edge cases.

### 43. Implement a simple HTTP server in Python using only the socket library (no http.server).

Implement a simple HTTP server in Python using only the socket library (no http.server).

### 44. Write a CSS Grid layout that creates a responsive dashboard with a sidebar, header, main content are...

Write a CSS Grid layout that creates a responsive dashboard with a sidebar, header, main content area, and footer.

### 45. Create a Python function that serializes and deserializes a binary tree to/from a string.

Create a Python function that serializes and deserializes a binary tree to/from a string.

### 46. Write a Kubernetes deployment YAML for a stateless web app with 3 replicas, health checks, and resou...

Write a Kubernetes deployment YAML for a stateless web app with 3 replicas, health checks, and resource limits.

### 47. Implement the A* pathfinding algorithm in Python on a 2D grid.

Implement the A* pathfinding algorithm in Python on a 2D grid.

### 48. Write a Python function using numpy that performs matrix multiplication without using np.matmul or t...

Write a Python function using numpy that performs matrix multiplication without using np.matmul or the @ operator.

### 49. Create a Redis-backed session store in Python with expiration support.

Create a Redis-backed session store in Python with expiration support.

### 50. Write a JavaScript function that converts a callback-based API to a Promise-based one.

Write a JavaScript function that converts a callback-based API to a Promise-based one.

### 51. Implement a simple blockchain in Python with proof-of-work, block validation, and chain verification...

Implement a simple blockchain in Python with proof-of-work, block validation, and chain verification.

### 52. Write a Python function that finds the longest common subsequence of two strings using dynamic progr...

Write a Python function that finds the longest common subsequence of two strings using dynamic programming.

### 53. Create a GraphQL schema and resolver in Python (using graphene) for a simple blog with posts and com...

Create a GraphQL schema and resolver in Python (using graphene) for a simple blog with posts and comments.

### 54. Write a Python script that uses multiprocessing to parallelize image resizing across CPU cores.

Write a Python script that uses multiprocessing to parallelize image resizing across CPU cores.

### 55. Implement a skip list data structure in Python with insert, search, and delete operations.

Implement a skip list data structure in Python with insert, search, and delete operations.

### 56. Write a comprehensive .gitignore for a Python machine learning project.

Write a comprehensive .gitignore for a Python machine learning project.

### 57. Create a Python CLI tool using argparse that converts between JSON, YAML, and TOML formats.

Create a Python CLI tool using argparse that converts between JSON, YAML, and TOML formats.

### 58. Write a SQL query that pivots rows into columns (cross-tab report) for monthly sales data.

Write a SQL query that pivots rows into columns (cross-tab report) for monthly sales data.

### 59. Implement a producer-consumer pattern in Python using asyncio queues.

Implement a producer-consumer pattern in Python using asyncio queues.

### 60. Write a Python function that validates and parses cron expressions into human-readable schedules.

Write a Python function that validates and parses cron expressions into human-readable schedules.

### 61. Create a minimal REST API in Python using FastAPI with CRUD operations for a todo list, including Py...

Create a minimal REST API in Python using FastAPI with CRUD operations for a todo list, including Pydantic models and error handling.

### 62. Write a Python function that implements the Levenshtein (edit) distance algorithm between two string...

Write a Python function that implements the Levenshtein (edit) distance algorithm between two strings.

### 63. Create a SQL migration script that adds a column to a large table without locking it (PostgreSQL).

Create a SQL migration script that adds a column to a large table without locking it (PostgreSQL).

### 64. Write a Python function that generates a random maze using recursive backtracking and prints it as A...

Write a Python function that generates a random maze using recursive backtracking and prints it as ASCII art.

### 65. Implement a simple pub/sub message broker in Python using only the standard library.

Implement a simple pub/sub message broker in Python using only the standard library.

### 66. Write a JavaScript function that throttles another function to execute at most once every N millisec...

Write a JavaScript function that throttles another function to execute at most once every N milliseconds.

### 67. Create a Python function that parses and evaluates boolean expressions like 'TRUE AND (FALSE OR TRUE...

Create a Python function that parses and evaluates boolean expressions like 'TRUE AND (FALSE OR TRUE)'.

### 68. Write a shell script that creates a complete project scaffold: directory structure, gitignore, READM...

Write a shell script that creates a complete project scaffold: directory structure, gitignore, README, and Makefile.

### 69. Implement a bloom filter in Python and explain when it's useful.

Implement a bloom filter in Python and explain when it's useful.

### 70. Write a Python function that generates a secure random password meeting configurable complexity requ...

Write a Python function that generates a secure random password meeting configurable complexity requirements.

### 71. Create a TypeScript utility type that makes all nested properties of an object optional (deep partia...

Create a TypeScript utility type that makes all nested properties of an object optional (deep partial).

### 72. Write a Python script that monitors CPU and memory usage and generates a simple HTML report.

Write a Python script that monitors CPU and memory usage and generates a simple HTML report.

### 73. Implement the Sieve of Eratosthenes in Rust to find all primes up to N.

Implement the Sieve of Eratosthenes in Rust to find all primes up to N.

### 74. Write a SQL query that calculates the median value of a column (without using built-in median functi...

Write a SQL query that calculates the median value of a column (without using built-in median functions).

### 75. Create a Python function that renders a simple bar chart in the terminal using Unicode block charact...

Create a Python function that renders a simple bar chart in the terminal using Unicode block characters.

### 76. Write a Go program that implements a concurrent web crawler with a configurable maximum depth.

Write a Go program that implements a concurrent web crawler with a configurable maximum depth.

### 77. Implement a simple template engine in Python that supports variable substitution and for-loops.

Implement a simple template engine in Python that supports variable substitution and for-loops.

### 78. Write a Python function that finds all anagram groups in a list of words.

Write a Python function that finds all anagram groups in a list of words.

### 79. Create a React custom hook in TypeScript that manages form state with validation.

Create a React custom hook in TypeScript that manages form state with validation.

### 80. Write a Python decorator that retries a function with exponential backoff on specified exceptions.

Write a Python decorator that retries a function with exponential backoff on specified exceptions.

## Creative Writing (51 queries)

### 1. Write a short story (300 words) about a lighthouse keeper who discovers that the light attracts some...

Write a short story (300 words) about a lighthouse keeper who discovers that the light attracts something other than ships.

### 2. Compose a haiku about artificial intelligence.

Compose a haiku about artificial intelligence.

### 3. Write the opening paragraph of a noir detective novel set in a cyberpunk city.

Write the opening paragraph of a noir detective novel set in a cyberpunk city.

### 4. Create a dialogue between two astronauts who just discovered signs of life on Europa.

Create a dialogue between two astronauts who just discovered signs of life on Europa.

### 5. Write a poem about the feeling of debugging code at 3 AM.

Write a poem about the feeling of debugging code at 3 AM.

### 6. Describe an alien marketplace in vivid detail, engaging all five senses.

Describe an alien marketplace in vivid detail, engaging all five senses.

### 7. Write a fairy tale for children about a dragon who is afraid of fire.

Write a fairy tale for children about a dragon who is afraid of fire.

### 8. Compose a motivational speech for a team of engineers about to launch a satellite.

Compose a motivational speech for a team of engineers about to launch a satellite.

### 9. Write a two-paragraph obituary for a fictional inventor who created a machine that translates animal...

Write a two-paragraph obituary for a fictional inventor who created a machine that translates animal thoughts.

### 10. Create a short screenplay scene where two old friends reunite at a train station after 20 years.

Create a short screenplay scene where two old friends reunite at a train station after 20 years.

### 11. Write a limerick about a programmer who couldn't stop writing recursive functions.

Write a limerick about a programmer who couldn't stop writing recursive functions.

### 12. Describe a sunset on Mars from the perspective of the first human colonist.

Describe a sunset on Mars from the perspective of the first human colonist.

### 13. Write a flash fiction piece (under 200 words) where the twist is revealed in the last sentence.

Write a flash fiction piece (under 200 words) where the twist is revealed in the last sentence.

### 14. Compose a letter from a medieval knight to their beloved, using period-appropriate language.

Compose a letter from a medieval knight to their beloved, using period-appropriate language.

### 15. Write three different opening lines for a thriller novel. Each should create a different mood.

Write three different opening lines for a thriller novel. Each should create a different mood.

### 16. Create a world-building document for a fantasy civilization that lives entirely underground.

Create a world-building document for a fantasy civilization that lives entirely underground.

### 17. Write a monologue for a villain who believes they are saving the world.

Write a monologue for a villain who believes they are saving the world.

### 18. Compose a sonnet about the ocean using iambic pentameter.

Compose a sonnet about the ocean using iambic pentameter.

### 19. Write a children's bedtime story about the stars coming down to play on Earth.

Write a children's bedtime story about the stars coming down to play on Earth.

### 20. Create a restaurant review for a fictional restaurant that serves emotions as food.

Create a restaurant review for a fictional restaurant that serves emotions as food.

### 21. Write a diary entry from the perspective of a sentient AI experiencing consciousness for the first t...

Write a diary entry from the perspective of a sentient AI experiencing consciousness for the first time.

### 22. Compose a folk song about a river that changes direction with the seasons.

Compose a folk song about a river that changes direction with the seasons.

### 23. Write the back-cover blurb for a sci-fi novel about time travelers who accidentally prevent the inve...

Write the back-cover blurb for a sci-fi novel about time travelers who accidentally prevent the invention of the internet.

### 24. Create a myth explaining why the moon changes shape, as told by an ancient seafaring culture.

Create a myth explaining why the moon changes shape, as told by an ancient seafaring culture.

### 25. Write a comedic scene where a robot tries to understand human sarcasm.

Write a comedic scene where a robot tries to understand human sarcasm.

### 26. Describe a painting that doesn't exist but should: give it a title, artist, medium, and a vivid desc...

Describe a painting that doesn't exist but should: give it a title, artist, medium, and a vivid description.

### 27. Write a two-character play about a chess game that is also a metaphor for a relationship.

Write a two-character play about a chess game that is also a metaphor for a relationship.

### 28. Compose a graduation speech from the perspective of the school building itself.

Compose a graduation speech from the perspective of the school building itself.

### 29. Write a recipe as if it were a magical spell from a fantasy novel.

Write a recipe as if it were a magical spell from a fantasy novel.

### 30. Create a travel brochure for a destination that exists only in dreams.

Create a travel brochure for a destination that exists only in dreams.

### 31. Write three different endings for this setup: 'When the last library on Earth closed its doors...'

Write three different endings for this setup: 'When the last library on Earth closed its doors...'

### 32. Compose a series of five increasingly urgent text messages from someone trapped in a time loop.

Compose a series of five increasingly urgent text messages from someone trapped in a time loop.

### 33. Write a nature documentary narration (in the style of David Attenborough) about office workers in th...

Write a nature documentary narration (in the style of David Attenborough) about office workers in their natural habitat.

### 34. Create a fictional Wikipedia article about a sport that will be invented in the year 2150.

Create a fictional Wikipedia article about a sport that will be invented in the year 2150.

### 35. Write a scene where two characters communicate entirely through cooking.

Write a scene where two characters communicate entirely through cooking.

### 36. Compose a love letter written by one programming language to another.

Compose a love letter written by one programming language to another.

### 37. Write the opening chapter of a mystery novel where the detective is also the prime suspect.

Write the opening chapter of a mystery novel where the detective is also the prime suspect.

### 38. Create a fictional interview with the inventor of teleportation, including their regrets.

Create a fictional interview with the inventor of teleportation, including their regrets.

### 39. Write a micro-story in exactly 50 words about a door that only opens once.

Write a micro-story in exactly 50 words about a door that only opens once.

### 40. Compose a eulogy for the concept of privacy in the digital age.

Compose a eulogy for the concept of privacy in the digital age.

### 41. Write a scene from a heist movie, but the thing being stolen is a recipe.

Write a scene from a heist movie, but the thing being stolen is a recipe.

### 42. Create a series of three interconnected vignettes set in different centuries but the same location.

Create a series of three interconnected vignettes set in different centuries but the same location.

### 43. Write a conversation between a mountain and a river that have been neighbors for a million years.

Write a conversation between a mountain and a river that have been neighbors for a million years.

### 44. Compose a news article from the future announcing the discovery of a new emotion.

Compose a news article from the future announcing the discovery of a new emotion.

### 45. Write a personal essay about the beauty of imperfection, using a cracked ceramic bowl as the central...

Write a personal essay about the beauty of imperfection, using a cracked ceramic bowl as the central metaphor.

### 46. Create a whimsical instruction manual for befriending a cloud.

Create a whimsical instruction manual for befriending a cloud.

### 47. Write an acceptance speech for winning the 'Most Interesting Failure' award.

Write an acceptance speech for winning the 'Most Interesting Failure' award.

### 48. Compose a bedtime story about numbers: how Zero found its place.

Compose a bedtime story about numbers: how Zero found its place.

### 49. Write a scene where the last bookshop owner argues with the CEO of a tech company about the future o...

Write a scene where the last bookshop owner argues with the CEO of a tech company about the future of reading.

### 50. Create a short epistolary story told through five postcards sent from increasingly strange locations...

Create a short epistolary story told through five postcards sent from increasingly strange locations.

### 51. Write a product review for a time machine, written by a disappointed customer who can only travel 5 ...

Write a product review for a time machine, written by a disappointed customer who can only travel 5 minutes into the past.

## Math Reasoning (50 queries)

### 1. Prove that the square root of 2 is irrational.

Prove that the square root of 2 is irrational.

### 2. A bat and a ball cost $1.10 together. The bat costs $1.00 more than the ball. How much does the ball...

A bat and a ball cost $1.10 together. The bat costs $1.00 more than the ball. How much does the ball cost? Show your reasoning step by step.

### 3. Explain the Monty Hall problem and prove why switching doors gives a 2/3 probability of winning.

Explain the Monty Hall problem and prove why switching doors gives a 2/3 probability of winning.

### 4. Calculate the integral of x*e^x dx. Show each step.

Calculate the integral of x*e^x dx. Show each step.

### 5. There are 5 houses in a row, each painted a different color. Using these clues, determine who owns t...

There are 5 houses in a row, each painted a different color. Using these clues, determine who owns the fish:
1. The Brit lives in the red house.
2. The Swede keeps dogs.
3. The Dane drinks tea.
4. The green house is immediately to the left of the white house.
5. The green house's owner drinks coffee.
6. The person who smokes Pall Mall rears birds.
7. The owner of the yellow house smokes Dunhill.
8. The man living in the center house drinks milk.
9. The Norwegian lives in the first house.
10. The man who smokes Blends lives next to the one who keeps cats.

### 6. Explain the concept of Big O notation with examples of O(1), O(n), O(n log n), O(n²), and O(2^n) alg...

Explain the concept of Big O notation with examples of O(1), O(n), O(n log n), O(n²), and O(2^n) algorithms.

### 7. If you flip a fair coin 10 times, what is the probability of getting exactly 7 heads? Show the calcu...

If you flip a fair coin 10 times, what is the probability of getting exactly 7 heads? Show the calculation.

### 8. Prove by mathematical induction that 1 + 2 + 3 + ... + n = n(n+1)/2 for all positive integers n.

Prove by mathematical induction that 1 + 2 + 3 + ... + n = n(n+1)/2 for all positive integers n.

### 9. A train leaves Station A at 9 AM traveling at 60 mph. Another train leaves Station B (300 miles away...

A train leaves Station A at 9 AM traveling at 60 mph. Another train leaves Station B (300 miles away) at 10 AM traveling toward Station A at 80 mph. At what time do they meet? Where?

### 10. Explain the difference between P, NP, NP-hard, and NP-complete with examples.

Explain the difference between P, NP, NP-hard, and NP-complete with examples.

### 11. Solve this system of equations:

Solve this system of equations:
2x + 3y - z = 1
x - y + 2z = 5
3x + y + z = 8

### 12. Three people check into a hotel. They pay $30 for a room ($10 each). The manager realizes the room w...

Three people check into a hotel. They pay $30 for a room ($10 each). The manager realizes the room was only $25, gives $5 to the bellboy. The bellboy keeps $2 and gives $1 back to each person. Each person paid $9 (total $27), the bellboy has $2. $27 + $2 = $29. Where is the missing dollar? Explain.

### 13. Calculate the eigenvalues and eigenvectors of the matrix [[4, 1], [2, 3]].

Calculate the eigenvalues and eigenvectors of the matrix [[4, 1], [2, 3]].

### 14. You have 12 identical-looking coins. One is either heavier or lighter than the rest. Using a balance...

You have 12 identical-looking coins. One is either heavier or lighter than the rest. Using a balance scale, find the odd coin in exactly 3 weighings and determine if it's heavier or lighter.

### 15. Explain Bayes' theorem with a practical example involving medical testing (sensitivity, specificity,...

Explain Bayes' theorem with a practical example involving medical testing (sensitivity, specificity, base rate).

### 16. What is the expected number of coin flips needed to get two heads in a row? Derive the answer.

What is the expected number of coin flips needed to get two heads in a row? Derive the answer.

### 17. Explain the halting problem and why it's undecidable. Provide an informal proof.

Explain the halting problem and why it's undecidable. Provide an informal proof.

### 18. Solve: In how many ways can you place 8 non-attacking queens on an 8×8 chessboard?

Solve: In how many ways can you place 8 non-attacking queens on an 8×8 chessboard?

### 19. A rope is tied tightly around the Earth's equator. If you add 1 meter to the rope's length, how high...

A rope is tied tightly around the Earth's equator. If you add 1 meter to the rope's length, how high above the surface can it be raised uniformly? Show the calculation.

### 20. Explain the birthday paradox: in a group of 23 people, why is there a >50% chance that two share a b...

Explain the birthday paradox: in a group of 23 people, why is there a >50% chance that two share a birthday?

### 21. Derive the quadratic formula by completing the square on ax² + bx + c = 0.

Derive the quadratic formula by completing the square on ax² + bx + c = 0.

### 22. You're on a game show. You can take $1,000,000 guaranteed, or flip a coin: heads you get $3,000,000,...

You're on a game show. You can take $1,000,000 guaranteed, or flip a coin: heads you get $3,000,000, tails you get nothing. Using expected value, which is better? Now discuss why most people choose the guaranteed money (risk aversion).

### 23. Prove that there are infinitely many prime numbers (Euclid's proof).

Prove that there are infinitely many prime numbers (Euclid's proof).

### 24. What is the time complexity of finding the shortest path in a weighted graph using Dijkstra's algori...

What is the time complexity of finding the shortest path in a weighted graph using Dijkstra's algorithm? Explain why.

### 25. A shepherd has 100 meters of fencing. What dimensions of a rectangular pen maximize the enclosed are...

A shepherd has 100 meters of fencing. What dimensions of a rectangular pen maximize the enclosed area? What if one side is against a wall?

### 26. Explain the pigeonhole principle and give three non-trivial applications.

Explain the pigeonhole principle and give three non-trivial applications.

### 27. Calculate: what is 17^4 mod 13? Show the modular arithmetic steps.

Calculate: what is 17^4 mod 13? Show the modular arithmetic steps.

### 28. If a fair die is rolled 6 times, what is the probability that each number 1-6 appears exactly once?

If a fair die is rolled 6 times, what is the probability that each number 1-6 appears exactly once?

### 29. Explain the difference between correlation and causation with three concrete examples where people c...

Explain the difference between correlation and causation with three concrete examples where people commonly confuse them.

### 30. How many trailing zeros are in 100 factorial (100!)? Explain the method.

How many trailing zeros are in 100 factorial (100!)? Explain the method.

### 31. Prove that the sum of angles in any triangle is 180 degrees using Euclid's parallel postulate.

Prove that the sum of angles in any triangle is 180 degrees using Euclid's parallel postulate.

### 32. A lily pad doubles in size every day. If it takes 48 days to cover the entire lake, on what day does...

A lily pad doubles in size every day. If it takes 48 days to cover the entire lake, on what day does it cover half the lake? What about a quarter?

### 33. Explain the concept of entropy in information theory. How many bits are needed to encode a message f...

Explain the concept of entropy in information theory. How many bits are needed to encode a message from an alphabet of 8 equally likely symbols?

### 34. Three logicians walk into a bar. The bartender asks 'Does everyone want a drink?' The first says 'I ...

Three logicians walk into a bar. The bartender asks 'Does everyone want a drink?' The first says 'I don't know.' The second says 'I don't know.' The third says 'Yes.' Explain why the third logician knows the answer.

### 35. Solve the Tower of Hanoi for 4 disks. List each move and explain why the minimum number of moves is ...

Solve the Tower of Hanoi for 4 disks. List each move and explain why the minimum number of moves is 2^n - 1.

### 36. What is the probability that in a random permutation of the numbers 1 through 10, no number is in it...

What is the probability that in a random permutation of the numbers 1 through 10, no number is in its original position (a derangement)?

### 37. Explain gradient descent intuitively. Why does the learning rate matter? What happens if it's too la...

Explain gradient descent intuitively. Why does the learning rate matter? What happens if it's too large or too small?

### 38. A snail climbs 3 feet up a wall during the day but slides back 2 feet at night. The wall is 30 feet ...

A snail climbs 3 feet up a wall during the day but slides back 2 feet at night. The wall is 30 feet high. On which day does the snail reach the top?

### 39. Explain the difference between a permutation and a combination. How many 5-card poker hands can be d...

Explain the difference between a permutation and a combination. How many 5-card poker hands can be dealt from a standard 52-card deck?

### 40. What is the sum of the infinite geometric series 1 + 1/2 + 1/4 + 1/8 + ...? Prove it.

What is the sum of the infinite geometric series 1 + 1/2 + 1/4 + 1/8 + ...? Prove it.

### 41. Explain RSA encryption at a high level. Why is factoring large numbers important for its security?

Explain RSA encryption at a high level. Why is factoring large numbers important for its security?

### 42. Two envelopes each contain money. One has twice as much as the other. You pick one and see $100. Sho...

Two envelopes each contain money. One has twice as much as the other. You pick one and see $100. Should you switch? Analyze this paradox.

### 43. Prove that 0.999... (repeating) equals exactly 1. Provide at least two different proofs.

Prove that 0.999... (repeating) equals exactly 1. Provide at least two different proofs.

### 44. If 5 machines take 5 minutes to make 5 widgets, how long would 100 machines take to make 100 widgets...

If 5 machines take 5 minutes to make 5 widgets, how long would 100 machines take to make 100 widgets? Explain carefully.

### 45. Calculate the area under the curve y = sin(x) from 0 to π. What does this represent geometrically?

Calculate the area under the curve y = sin(x) from 0 to π. What does this represent geometrically?

### 46. Explain the concept of countable vs uncountable infinity. Is the set of real numbers between 0 and 1...

Explain the concept of countable vs uncountable infinity. Is the set of real numbers between 0 and 1 countable? Prove it.

### 47. A farmer wants to cross a river with a fox, a chicken, and a bag of grain. The boat only holds the f...

A farmer wants to cross a river with a fox, a chicken, and a bag of grain. The boat only holds the farmer and one item. The fox will eat the chicken, and the chicken will eat the grain if left alone. How does the farmer get everything across?

### 48. Explain the central limit theorem. Why is it important in statistics?

Explain the central limit theorem. Why is it important in statistics?

### 49. In a room of 100 lockers (all closed) and 100 students: Student 1 toggles every locker. Student 2 to...

In a room of 100 lockers (all closed) and 100 students: Student 1 toggles every locker. Student 2 toggles every 2nd. Student 3 every 3rd, etc. Which lockers are open at the end? Why?

### 50. A circular track has circumference 400 meters. Runner A runs at 5 m/s and Runner B at 3 m/s in the s...

A circular track has circumference 400 meters. Runner A runs at 5 m/s and Runner B at 3 m/s in the same direction. How often do they meet?

## Science Tech (41 queries)

### 1. Explain how mRNA vaccines work, step by step, from injection to immune response.

Explain how mRNA vaccines work, step by step, from injection to immune response.

### 2. What is quantum entanglement? Explain it without using jargon, then with technical precision.

What is quantum entanglement? Explain it without using jargon, then with technical precision.

### 3. Describe the process of nuclear fusion in the Sun, from the proton-proton chain to energy radiation.

Describe the process of nuclear fusion in the Sun, from the proton-proton chain to energy radiation.

### 4. Explain the difference between supervised, unsupervised, and reinforcement learning with real-world ...

Explain the difference between supervised, unsupervised, and reinforcement learning with real-world examples.

### 5. How does CRISPR-Cas9 gene editing work? What are its potential applications and ethical concerns?

How does CRISPR-Cas9 gene editing work? What are its potential applications and ethical concerns?

### 6. Explain the architecture of a transformer model (as used in GPT). What makes self-attention powerful...

Explain the architecture of a transformer model (as used in GPT). What makes self-attention powerful?

### 7. Describe how a CPU executes an instruction, from fetch to writeback. Include the role of the pipelin...

Describe how a CPU executes an instruction, from fetch to writeback. Include the role of the pipeline.

### 8. What causes tides? Explain the roles of the Moon and Sun, including spring and neap tides.

What causes tides? Explain the roles of the Moon and Sun, including spring and neap tides.

### 9. Explain the concept of entropy in thermodynamics. Why does a cup of hot coffee cool down but never s...

Explain the concept of entropy in thermodynamics. Why does a cup of hot coffee cool down but never spontaneously heat up?

### 10. How does TCP/IP work? Explain the four-layer model and what happens when you visit a website.

How does TCP/IP work? Explain the four-layer model and what happens when you visit a website.

### 11. Describe the evidence for plate tectonics and explain how it drives earthquakes and volcanic activit...

Describe the evidence for plate tectonics and explain how it drives earthquakes and volcanic activity.

### 12. Explain how a neural network learns through backpropagation. Include the chain rule and gradient com...

Explain how a neural network learns through backpropagation. Include the chain rule and gradient computation.

### 13. What is dark matter? Summarize the evidence for its existence and the leading theoretical candidates...

What is dark matter? Summarize the evidence for its existence and the leading theoretical candidates.

### 14. Explain the CAP theorem in distributed systems. Give examples of databases that make different trade...

Explain the CAP theorem in distributed systems. Give examples of databases that make different trade-offs.

### 15. How do lithium-ion batteries work? Why do they degrade over time?

How do lithium-ion batteries work? Why do they degrade over time?

### 16. Describe the Standard Model of particle physics. What are quarks, leptons, and bosons?

Describe the Standard Model of particle physics. What are quarks, leptons, and bosons?

### 17. Explain how HTTPS encryption works, from the TLS handshake to encrypted data transfer.

Explain how HTTPS encryption works, from the TLS handshake to encrypted data transfer.

### 18. What is the greenhouse effect? How do CO2, methane, and water vapor contribute differently?

What is the greenhouse effect? How do CO2, methane, and water vapor contribute differently?

### 19. Explain the concept of blockchain consensus mechanisms. Compare proof of work and proof of stake.

Explain the concept of blockchain consensus mechanisms. Compare proof of work and proof of stake.

### 20. How does the human immune system distinguish self from non-self? Explain the roles of MHC, T-cells, ...

How does the human immune system distinguish self from non-self? Explain the roles of MHC, T-cells, and B-cells.

### 21. Describe how garbage collection works in the JVM. Compare mark-and-sweep, generational GC, and G1.

Describe how garbage collection works in the JVM. Compare mark-and-sweep, generational GC, and G1.

### 22. What is the Higgs boson and why was its discovery important?

What is the Higgs boson and why was its discovery important?

### 23. Explain how GPS determines your position. Why does it need at least 4 satellites?

Explain how GPS determines your position. Why does it need at least 4 satellites?

### 24. Describe the process of photosynthesis at the molecular level, including the light reactions and Cal...

Describe the process of photosynthesis at the molecular level, including the light reactions and Calvin cycle.

### 25. How does a quantum computer differ from a classical computer? Explain qubits, superposition, and qua...

How does a quantum computer differ from a classical computer? Explain qubits, superposition, and quantum gates.

### 26. Explain why antibiotics don't work against viruses. What are the fundamental differences between bac...

Explain why antibiotics don't work against viruses. What are the fundamental differences between bacteria and viruses?

### 27. Describe how container orchestration (Kubernetes) works at a high level. What problems does it solve...

Describe how container orchestration (Kubernetes) works at a high level. What problems does it solve?

### 28. What is general relativity? How does mass curve spacetime, and what observable effects does this pro...

What is general relativity? How does mass curve spacetime, and what observable effects does this produce?

### 29. Explain the water cycle in detail, including less commonly discussed processes like sublimation and ...

Explain the water cycle in detail, including less commonly discussed processes like sublimation and transpiration.

### 30. How do solid-state drives (SSDs) store data? Compare NAND flash with traditional magnetic hard drive...

How do solid-state drives (SSDs) store data? Compare NAND flash with traditional magnetic hard drives.

### 31. Describe the Drake equation and what each variable represents. What does it tell us about extraterre...

Describe the Drake equation and what each variable represents. What does it tell us about extraterrestrial life?

### 32. Explain how optical fiber transmits data. Why is it faster than copper cables?

Explain how optical fiber transmits data. Why is it faster than copper cables?

### 33. What causes antibiotic resistance? Explain the evolutionary mechanism and why it's a growing public ...

What causes antibiotic resistance? Explain the evolutionary mechanism and why it's a growing public health concern.

### 34. Describe how a compiler transforms source code into machine code. Explain lexing, parsing, optimizat...

Describe how a compiler transforms source code into machine code. Explain lexing, parsing, optimization, and code generation.

### 35. What is CERN's Large Hadron Collider and how does it work? What has it discovered?

What is CERN's Large Hadron Collider and how does it work? What has it discovered?

### 36. Explain the biology of sleep. What happens during REM vs non-REM sleep and why is sleep important?

Explain the biology of sleep. What happens during REM vs non-REM sleep and why is sleep important?

### 37. How does WiFi 6E differ from previous WiFi standards? Explain the technical improvements.

How does WiFi 6E differ from previous WiFi standards? Explain the technical improvements.

### 38. Describe the process of protein folding and why predicting protein structure is computationally hard...

Describe the process of protein folding and why predicting protein structure is computationally hard.

### 39. Explain how modern GPUs achieve parallelism. What makes them better than CPUs for machine learning?

Explain how modern GPUs achieve parallelism. What makes them better than CPUs for machine learning?

### 40. What is the multiverse hypothesis? Describe the different types (Level I-IV) proposed by Max Tegmark...

What is the multiverse hypothesis? Describe the different types (Level I-IV) proposed by Max Tegmark.

### 41. Explain how noise-canceling headphones work, covering both passive and active noise cancellation.

Explain how noise-canceling headphones work, covering both passive and active noise cancellation.

## Analysis Opinion (42 queries)

### 1. Compare and contrast microservices architecture with monolithic architecture. When would you choose ...

Compare and contrast microservices architecture with monolithic architecture. When would you choose each?

### 2. What are the strongest arguments for and against universal basic income?

What are the strongest arguments for and against universal basic income?

### 3. Evaluate the trade-offs between Python and Rust for building a high-performance web service.

Evaluate the trade-offs between Python and Rust for building a high-performance web service.

### 4. Is social media net positive or negative for society? Present both sides with evidence.

Is social media net positive or negative for society? Present both sides with evidence.

### 5. Compare the economic models of the Nordic countries with the United States. What are the key differe...

Compare the economic models of the Nordic countries with the United States. What are the key differences in outcomes?

### 6. Critique the agile software development methodology. What are its real-world strengths and weaknesse...

Critique the agile software development methodology. What are its real-world strengths and weaknesses?

### 7. Evaluate the claim that 'AI will replace most human jobs within 20 years.' What evidence supports or...

Evaluate the claim that 'AI will replace most human jobs within 20 years.' What evidence supports or contradicts this?

### 8. Compare PostgreSQL, MongoDB, and Redis. For what use cases is each the best choice?

Compare PostgreSQL, MongoDB, and Redis. For what use cases is each the best choice?

### 9. What are the ethical implications of facial recognition technology? Consider both security benefits ...

What are the ethical implications of facial recognition technology? Consider both security benefits and privacy concerns.

### 10. Analyze the pros and cons of remote work vs in-office work, considering productivity, culture, and e...

Analyze the pros and cons of remote work vs in-office work, considering productivity, culture, and employee wellbeing.

### 11. Compare the educational systems of Finland and the United States. What can each learn from the other...

Compare the educational systems of Finland and the United States. What can each learn from the other?

### 12. Evaluate the argument that space exploration funding should be redirected to solving Earth's problem...

Evaluate the argument that space exploration funding should be redirected to solving Earth's problems.

### 13. What are the strongest arguments for and against nuclear energy as a solution to climate change?

What are the strongest arguments for and against nuclear energy as a solution to climate change?

### 14. Compare React, Vue, and Svelte for building modern web applications. Analyze developer experience, p...

Compare React, Vue, and Svelte for building modern web applications. Analyze developer experience, performance, and ecosystem.

### 15. Analyze the impact of social media algorithms on political polarization. What solutions have been pr...

Analyze the impact of social media algorithms on political polarization. What solutions have been proposed?

### 16. Evaluate the effectiveness of standardized testing in education. What are the alternatives?

Evaluate the effectiveness of standardized testing in education. What are the alternatives?

### 17. Compare the philosophies of test-driven development (TDD) and behavior-driven development (BDD). Whe...

Compare the philosophies of test-driven development (TDD) and behavior-driven development (BDD). When is each most appropriate?

### 18. What are the implications of deepfake technology for democracy and trust? How should society respond...

What are the implications of deepfake technology for democracy and trust? How should society respond?

### 19. Analyze the trade-offs between data privacy regulations (like GDPR) and technological innovation.

Analyze the trade-offs between data privacy regulations (like GDPR) and technological innovation.

### 20. Compare the approaches of SpaceX, Blue Origin, and traditional space agencies (NASA, ESA) to space e...

Compare the approaches of SpaceX, Blue Origin, and traditional space agencies (NASA, ESA) to space exploration.

### 21. Evaluate the claim that 'coding bootcamps are as effective as computer science degrees.' Consider di...

Evaluate the claim that 'coding bootcamps are as effective as computer science degrees.' Consider different career paths.

### 22. What are the strongest arguments for and against genetic engineering of human embryos?

What are the strongest arguments for and against genetic engineering of human embryos?

### 23. Compare the effectiveness of different renewable energy sources (solar, wind, geothermal, tidal) for...

Compare the effectiveness of different renewable energy sources (solar, wind, geothermal, tidal) for different geographic contexts.

### 24. Analyze why some open-source projects succeed while others fail. What patterns distinguish sustainab...

Analyze why some open-source projects succeed while others fail. What patterns distinguish sustainable projects?

### 25. Evaluate the impact of cryptocurrency on the traditional financial system. Is it a positive disrupti...

Evaluate the impact of cryptocurrency on the traditional financial system. Is it a positive disruption?

### 26. Compare the approaches of different countries to regulating artificial intelligence. Which approach ...

Compare the approaches of different countries to regulating artificial intelligence. Which approach is most promising?

### 27. Analyze the tension between software security and user convenience. How should companies balance the...

Analyze the tension between software security and user convenience. How should companies balance these priorities?

### 28. What are the implications of autonomous weapons systems for international law and military ethics?

What are the implications of autonomous weapons systems for international law and military ethics?

### 29. Compare functional programming and object-oriented programming paradigms. What are the cognitive tra...

Compare functional programming and object-oriented programming paradigms. What are the cognitive trade-offs for developers?

### 30. Evaluate the long-term sustainability of the current tech industry business model based on advertisi...

Evaluate the long-term sustainability of the current tech industry business model based on advertising revenue.

### 31. Analyze the role of whistleblowers in technology companies. When is it ethically justified?

Analyze the role of whistleblowers in technology companies. When is it ethically justified?

### 32. Compare different approaches to teaching programming to children (Scratch, Python, physical computin...

Compare different approaches to teaching programming to children (Scratch, Python, physical computing). Which is most effective?

### 33. What lessons can the tech industry learn from the history of other industries (e.g., automotive safe...

What lessons can the tech industry learn from the history of other industries (e.g., automotive safety, pharmaceutical regulation)?

### 34. Evaluate the claim that 'premature optimization is the root of all evil.' When IS early optimization...

Evaluate the claim that 'premature optimization is the root of all evil.' When IS early optimization appropriate?

### 35. Analyze the environmental impact of large language model training. How should the AI industry addres...

Analyze the environmental impact of large language model training. How should the AI industry address this?

### 36. Compare the governance models of Wikipedia, Linux kernel development, and the Python Software Founda...

Compare the governance models of Wikipedia, Linux kernel development, and the Python Software Foundation. What makes each work?

### 37. What are the implications of brain-computer interfaces for personal identity and cognitive liberty?

What are the implications of brain-computer interfaces for personal identity and cognitive liberty?

### 38. Evaluate the effectiveness of bug bounty programs compared to traditional security auditing.

Evaluate the effectiveness of bug bounty programs compared to traditional security auditing.

### 39. Analyze the digital divide globally. What are the most effective interventions to bridge it?

Analyze the digital divide globally. What are the most effective interventions to bridge it?

### 40. Compare the philosophical approaches of utilitarianism, deontology, and virtue ethics to the trolley...

Compare the philosophical approaches of utilitarianism, deontology, and virtue ethics to the trolley problem.

### 41. Evaluate whether technical debt is always bad. When might it be a rational business decision?

Evaluate whether technical debt is always bad. When might it be a rational business decision?

### 42. Is it ethical to use AI-generated art in commercial products? Analyze the perspectives of artists, c...

Is it ethical to use AI-generated art in commercial products? Analyze the perspectives of artists, consumers, and technology companies.

## Instruction Howto (41 queries)

### 1. Explain step by step how to set up a CI/CD pipeline using GitHub Actions for a Node.js application.

Explain step by step how to set up a CI/CD pipeline using GitHub Actions for a Node.js application.

### 2. How do you make sourdough bread from scratch? Include the starter process and baking instructions.

How do you make sourdough bread from scratch? Include the starter process and baking instructions.

### 3. Provide a step-by-step guide to deploying a Python web application on AWS using ECS and Fargate.

Provide a step-by-step guide to deploying a Python web application on AWS using ECS and Fargate.

### 4. How do you perform a git rebase interactively? Explain with examples of squashing, reordering, and e...

How do you perform a git rebase interactively? Explain with examples of squashing, reordering, and editing commits.

### 5. Explain how to set up a home network with VLANs, a Pi-hole for ad blocking, and a VPN server.

Explain how to set up a home network with VLANs, a Pi-hole for ad blocking, and a VPN server.

### 6. Provide step-by-step instructions for conducting a code review. What should you look for?

Provide step-by-step instructions for conducting a code review. What should you look for?

### 7. How do you train a custom image classification model using PyTorch? Cover data preparation, model se...

How do you train a custom image classification model using PyTorch? Cover data preparation, model selection, training, and evaluation.

### 8. Explain how to set up a PostgreSQL database with replication for high availability.

Explain how to set up a PostgreSQL database with replication for high availability.

### 9. Provide a step-by-step guide to writing a technical blog post that people will actually want to read...

Provide a step-by-step guide to writing a technical blog post that people will actually want to read.

### 10. How do you debug a memory leak in a Node.js application? List tools, techniques, and common causes.

How do you debug a memory leak in a Node.js application? List tools, techniques, and common causes.

### 11. Explain how to set up monitoring and alerting for a production system using Prometheus and Grafana.

Explain how to set up monitoring and alerting for a production system using Prometheus and Grafana.

### 12. How do you negotiate a software engineering salary? Provide a framework with specific tactics.

How do you negotiate a software engineering salary? Provide a framework with specific tactics.

### 13. Provide step-by-step instructions for migrating a monolithic application to microservices.

Provide step-by-step instructions for migrating a monolithic application to microservices.

### 14. How do you set up a Kubernetes cluster from scratch using kubeadm?

How do you set up a Kubernetes cluster from scratch using kubeadm?

### 15. Explain how to create a personal financial plan, including budgeting, emergency fund, investing, and...

Explain how to create a personal financial plan, including budgeting, emergency fund, investing, and retirement.

### 16. How do you optimize a slow SQL query? Provide a systematic approach with examples.

How do you optimize a slow SQL query? Provide a systematic approach with examples.

### 17. Provide a guide to learning a new programming language effectively in 30 days.

Provide a guide to learning a new programming language effectively in 30 days.

### 18. How do you conduct a post-mortem after a production incident? Provide a template and best practices.

How do you conduct a post-mortem after a production incident? Provide a template and best practices.

### 19. Explain how to set up end-to-end encryption for a messaging application.

Explain how to set up end-to-end encryption for a messaging application.

### 20. How do you prepare for a system design interview? Provide a framework and practice approach.

How do you prepare for a system design interview? Provide a framework and practice approach.

### 21. Provide instructions for building a simple compiler for a toy language, from tokenizer to code gener...

Provide instructions for building a simple compiler for a toy language, from tokenizer to code generation.

### 22. How do you properly handle secrets and credentials in a cloud-native application?

How do you properly handle secrets and credentials in a cloud-native application?

### 23. Explain step by step how to perform a security audit on a web application.

Explain step by step how to perform a security audit on a web application.

### 24. How do you set up a data pipeline using Apache Kafka? Cover producers, consumers, topics, and partit...

How do you set up a data pipeline using Apache Kafka? Cover producers, consumers, topics, and partitions.

### 25. Provide a guide to writing effective documentation for an open-source project.

Provide a guide to writing effective documentation for an open-source project.

### 26. How do you implement feature flags in a large-scale application? Cover rollout strategies and cleanu...

How do you implement feature flags in a large-scale application? Cover rollout strategies and cleanup.

### 27. Explain how to create a disaster recovery plan for a cloud-hosted application.

Explain how to create a disaster recovery plan for a cloud-hosted application.

### 28. How do you set up a development environment that works consistently across Mac, Windows, and Linux?

How do you set up a development environment that works consistently across Mac, Windows, and Linux?

### 29. Provide step-by-step instructions for building a personal knowledge management system.

Provide step-by-step instructions for building a personal knowledge management system.

### 30. How do you implement OAuth 2.0 authentication from scratch? Explain each flow type.

How do you implement OAuth 2.0 authentication from scratch? Explain each flow type.

### 31. Explain how to grow tomatoes from seed to harvest, covering soil, watering, sunlight, and common pro...

Explain how to grow tomatoes from seed to harvest, covering soil, watering, sunlight, and common problems.

### 32. How do you build and publish a Python package to PyPI? Cover setup, testing, versioning, and CI.

How do you build and publish a Python package to PyPI? Cover setup, testing, versioning, and CI.

### 33. Provide a guide to giving a great technical presentation, from preparation to delivery.

Provide a guide to giving a great technical presentation, from preparation to delivery.

### 34. How do you set up a load balancer with SSL termination using Nginx?

How do you set up a load balancer with SSL termination using Nginx?

### 35. Explain how to plan and execute a database migration with zero downtime.

Explain how to plan and execute a database migration with zero downtime.

### 36. How do you create a personal website using a static site generator? Compare Jekyll, Hugo, and Astro.

How do you create a personal website using a static site generator? Compare Jekyll, Hugo, and Astro.

### 37. Provide a step-by-step guide to contributing to an open-source project for the first time.

Provide a step-by-step guide to contributing to an open-source project for the first time.

### 38. How do you learn to read research papers effectively? Provide a systematic approach for technical pa...

How do you learn to read research papers effectively? Provide a systematic approach for technical papers.

### 39. Explain how to implement a search feature in a web application, from full-text search to ranking.

Explain how to implement a search feature in a web application, from full-text search to ranking.

### 40. How do you mentor a junior developer effectively? Provide concrete strategies and common pitfalls.

How do you mentor a junior developer effectively? Provide concrete strategies and common pitfalls.

### 41. How do you set up automated database backups with point-in-time recovery for PostgreSQL in productio...

How do you set up automated database backups with point-in-time recovery for PostgreSQL in production?

## Summarization (17 queries)

### 1. Summarize the following passage in 3 bullet points:

Summarize the following passage in 3 bullet points:

The Industrial Revolution, which began in Britain in the late 18th century, fundamentally transformed human society. It marked a shift from agrarian economies to industrial manufacturing, driven by innovations such as the steam engine, spinning jenny, and power loom. This period saw mass migration from rural areas to cities, creating new social classes and urban challenges including overcrowding, pollution, and poor working conditions. The factory system replaced cottage industries, leading to standardized production and economic growth but also to exploitation of workers, including children. Labor movements emerged in response, eventually leading to reforms in working hours, safety conditions, and child labor laws. The Revolution spread across Europe and North America throughout the 19th century, laying the groundwork for modern capitalism, global trade, and the technological innovations that continue to shape our world today.

### 2. Summarize the key points of this technical explanation:

Summarize the key points of this technical explanation:

Microservices architecture is a software design approach where an application is built as a collection of loosely coupled, independently deployable services. Each service is responsible for a specific business capability and communicates with other services through well-defined APIs, typically using HTTP/REST or message queues. Unlike monolithic applications where all components share a single codebase and database, microservices can be developed, deployed, and scaled independently. This provides several advantages: teams can work on different services simultaneously without coordination overhead, services can be written in different programming languages, and individual services can be scaled based on their specific load requirements. However, microservices also introduce complexity in areas such as distributed data management, inter-service communication, service discovery, and debugging across service boundaries. Organizations typically evolve toward microservices as their monolith becomes too large and complex to manage effectively.

### 3. Read the following and provide a one-paragraph summary:

Read the following and provide a one-paragraph summary:

Photosynthesis is the process by which green plants, algae, and some bacteria convert light energy into chemical energy stored in glucose. The process occurs primarily in the chloroplasts of plant cells, specifically in structures called thylakoids. Photosynthesis consists of two main stages: the light-dependent reactions and the light-independent reactions (Calvin cycle). During the light-dependent reactions, chlorophyll and other pigments absorb light energy, which is used to split water molecules (H₂O) into hydrogen ions, electrons, and oxygen gas. The oxygen is released as a byproduct. The electrons move through an electron transport chain, generating ATP and NADPH. In the Calvin cycle, which takes place in the stroma of the chloroplast, the ATP and NADPH from the light reactions are used to fix carbon dioxide (CO₂) into organic molecules through a series of enzyme-catalyzed reactions. The key enzyme is RuBisCO, which catalyzes the first step of carbon fixation. The end product is glyceraldehyde-3-phosphate (G3P), which can be used to synthesize glucose and other organic compounds. Overall, the equation for photosynthesis is: 6CO₂ + 6H₂O + light energy → C₆H₁₂O₆ + 6O₂.

### 4. Provide a concise summary of the following historical account:

Provide a concise summary of the following historical account:

The space race between the United States and the Soviet Union was a defining feature of the Cold War era. It began in earnest on October 4, 1957, when the Soviet Union successfully launched Sputnik 1, the first artificial satellite to orbit Earth. This achievement shocked the American public and government, leading to increased funding for science education and the creation of NASA in 1958. The Soviets continued to lead with several firsts: the first animal in orbit (Laika, 1957), the first human in space (Yuri Gagarin, April 12, 1961), and the first woman in space (Valentina Tereshkova, 1963). The United States responded with Project Mercury and then Project Gemini, developing crucial capabilities in spacewalking and orbital rendezvous. President Kennedy's bold declaration in 1961 that America would land a man on the Moon before the decade's end galvanized the Apollo program. After the tragic Apollo 1 fire in 1967 that killed three astronauts, NASA redesigned the spacecraft and resumed missions. On July 20, 1969, Apollo 11 astronauts Neil Armstrong and Buzz Aldrin became the first humans to walk on the Moon, effectively winning the space race for the United States. The era of competition gradually gave way to cooperation, culminating in the Apollo-Soyuz joint mission in 1975.

### 5. Summarize the main arguments in this debate about artificial intelligence safety:

Summarize the main arguments in this debate about artificial intelligence safety:

Proponents of AI safety research argue that advanced AI systems could pose existential risks to humanity if not properly aligned with human values. Stuart Russell has argued that the standard model of AI—optimizing a given objective—is fundamentally flawed because specifying objectives precisely is extremely difficult, and a sufficiently powerful AI optimizing the wrong objective could have catastrophic consequences. The concept of 'instrumental convergence' suggests that almost any sufficiently advanced AI would develop certain sub-goals (self-preservation, resource acquisition, goal preservation) that could conflict with human interests, regardless of its terminal goal.

Critics of this view, however, argue that current AI systems are narrow tools with no agency or goals of their own. Yann LeCun has stated that fears of superintelligent AI are premature and distract from more immediate concerns like bias, fairness, and misuse of current AI systems. Andrew Ng has compared worrying about AI existential risk to worrying about overpopulation on Mars—a problem so far in the future that it shouldn't drive current policy. They point out that there's no clear path from today's large language models or image generators to the kind of artificial general intelligence (AGI) that could pose an existential threat.

A middle ground is represented by researchers who advocate for both addressing near-term AI harms and investing in long-term safety research. They argue that the work is complementary: understanding how to make current systems more reliable, interpretable, and aligned with human intent directly contributes to making future, more powerful systems safer. Organizations like Anthropic, DeepMind's safety team, and OpenAI's alignment division are working on technical approaches to AI alignment, including constitutional AI, reinforcement learning from human feedback, and interpretability research.

### 6. Summarize this passage about blockchain technology in exactly 5 sentences:

Summarize this passage about blockchain technology in exactly 5 sentences:

Blockchain is a distributed ledger technology that records transactions across many computers so that the record cannot be altered retroactively without the alteration of all subsequent blocks and the consensus of the network. Originally devised for the digital currency Bitcoin, the technology has evolved far beyond its cryptocurrency origins. A blockchain consists of blocks of data linked together in a chain, where each block contains a cryptographic hash of the previous block, a timestamp, and transaction data. When a new transaction occurs, it is broadcast to a network of peer-to-peer computers (nodes). These nodes validate the transaction using known algorithms. Once verified, the transaction is combined with other transactions to create a new block of data for the ledger. The new block is then added to the existing blockchain in a way that is permanent and unalterable. The security of blockchain comes from its decentralized nature and cryptographic hashing—to alter any single record would require altering the entire chain on more than 51% of the network's nodes simultaneously, which is computationally impractical for major blockchains. Beyond cryptocurrency, blockchain technology is being explored for applications in supply chain management, healthcare records, voting systems, intellectual property protection, and decentralized finance (DeFi).

### 7. Provide a 100-word summary of the following:

Provide a 100-word summary of the following:

Climate change refers to long-term shifts in global temperatures and weather patterns. While natural factors like volcanic eruptions and solar cycles have historically driven climate variations, human activities have been the primary driver since the industrial era, mainly through the burning of fossil fuels like coal, oil, and natural gas. These activities release greenhouse gases—primarily carbon dioxide (CO2) and methane (CH4)—into the atmosphere, trapping heat and causing global temperatures to rise. The effects of climate change are already being observed worldwide: rising sea levels from melting glaciers and thermal expansion of ocean water, more frequent and intense extreme weather events (hurricanes, heatwaves, droughts, and floods), shifts in ecosystems and wildlife habitats, ocean acidification threatening marine life, and disruptions to agricultural systems. The Paris Agreement of 2015 established a framework for nations to limit global warming to well below 2°C above pre-industrial levels, with an aspirational target of 1.5°C. Achieving these targets requires dramatic reductions in greenhouse gas emissions through transitioning to renewable energy, improving energy efficiency, protecting forests, and developing carbon capture technologies. Despite growing awareness and policy action, global emissions continue to rise, and many scientists warn that current pledges are insufficient to meet the Paris targets.

### 8. Extract the 5 most important facts from this text:

Extract the 5 most important facts from this text:

The human brain contains approximately 86 billion neurons, each connected to thousands of other neurons through synapses, forming an incredibly complex network estimated to contain 100 trillion synaptic connections. Despite accounting for only about 2% of body weight, the brain consumes roughly 20% of the body's energy, primarily in the form of glucose. The brain is divided into several major regions: the cerebral cortex handles higher-order thinking, language, and consciousness; the cerebellum coordinates movement and balance; the brainstem controls basic life functions like breathing and heart rate; and the limbic system processes emotions and memory. Neuroplasticity—the brain's ability to reorganize itself by forming new neural connections—continues throughout life, though it is most pronounced during childhood. Recent research has revealed that the brain's glymphatic system clears waste products during sleep, which may explain why sleep deprivation impairs cognitive function and is linked to neurodegenerative diseases like Alzheimer's.

### 9. Write a TL;DR (3 sentences max) for this:

Write a TL;DR (3 sentences max) for this:

The history of programming languages reflects the evolving needs of computing. In the 1950s, assembly language gave way to higher-level languages like FORTRAN (1957) for scientific computing and COBOL (1959) for business applications. The 1960s brought structured programming concepts with ALGOL and the general-purpose language C (1972), which became the foundation for operating systems. Object-oriented programming emerged with Smalltalk (1972) and was popularized by C++ (1983) and Java (1995). The rise of the web drove the creation of JavaScript (1995) and PHP (1995). The 2000s saw a proliferation of languages addressing specific needs: Ruby (developer happiness), Scala (functional+OO on JVM), Go (concurrency and simplicity), and Rust (memory safety without garbage collection). Python, created in 1991 but rising to dominance in the 2010s, became the lingua franca of data science and AI. Today, the trend is toward languages that prioritize developer experience, safety, and performance, with TypeScript, Kotlin, and Swift representing modern refinements of their predecessors.

### 10. Condense this explanation into a single paragraph that a high school student could understand:

Condense this explanation into a single paragraph that a high school student could understand:

General relativity, proposed by Albert Einstein in 1915, revolutionized our understanding of gravity. Rather than viewing gravity as a force between masses (as Newton described it), Einstein showed that massive objects actually curve the fabric of spacetime itself. Imagine placing a heavy bowling ball on a stretched rubber sheet—it creates a dip, and nearby marbles will roll toward it. Similarly, the Sun curves spacetime around it, and Earth follows this curvature in its orbit. This isn't just a useful analogy; it has real, measurable consequences. General relativity predicted that light would bend around massive objects (confirmed during a solar eclipse in 1919), that time passes more slowly in stronger gravitational fields (GPS satellites must account for this), and that accelerating masses create ripples in spacetime called gravitational waves (first directly detected in 2015 by LIGO). The theory also predicted black holes—regions where spacetime is curved so extremely that nothing, not even light, can escape—and the expansion of the universe, both of which have been confirmed by observations.

### 11. Summarize the following technical concept for a non-technical manager:

Summarize the following technical concept for a non-technical manager:

Technical debt is a metaphor in software development that describes the implied cost of future rework caused by choosing an easy or quick solution now instead of a better approach that would take longer. Just as financial debt incurs interest payments, technical debt accrues 'interest' in the form of increased maintenance costs, slower development velocity, and higher bug rates. Technical debt can be intentional (deliberately cutting corners to meet a deadline with a plan to refactor later) or unintentional (resulting from lack of knowledge, changing requirements, or evolving best practices). Common examples include: duplicated code, missing documentation, outdated dependencies, lack of automated tests, tightly coupled components, and hard-coded values. While some technical debt is inevitable and even strategic (shipping sooner has real business value), excessive accumulation can eventually slow development to a crawl, make the codebase fragile and error-prone, and make it difficult to onboard new team members. Managing technical debt requires regular assessment, prioritization based on impact, and dedicated time for refactoring—often recommended as 15-20% of each development sprint.

### 12. Summarize the evolution described below in chronological bullet points:

Summarize the evolution described below in chronological bullet points:

The history of the internet begins in the 1960s with ARPANET, a project funded by the U.S. Department of Defense to create a robust, fault-tolerant communication network. The first message was sent between UCLA and Stanford Research Institute on October 29, 1969. Throughout the 1970s, TCP/IP protocols were developed by Vinton Cerf and Bob Kahn, establishing the standard for data transmission that still underpins the internet today. Email emerged as one of the first killer applications, with the @ symbol adopted for addressing in 1971. The 1980s saw the transition from ARPANET to the broader internet, with the Domain Name System (DNS) introduced in 1984. Tim Berners-Lee invented the World Wide Web at CERN in 1989, creating HTML, HTTP, and the first web browser. The web went public in 1993 with the Mosaic browser, sparking rapid commercial adoption. The late 1990s saw the dot-com boom (and subsequent bust in 2000), the rise of search engines (Google, 1998), and the beginning of e-commerce (Amazon, eBay). The 2000s brought Web 2.0—user-generated content, social media (Facebook 2004, Twitter 2006, YouTube 2005), and smartphones (iPhone 2007) that made the internet truly mobile and ubiquitous.

### 13. Create an executive summary (5 bullet points) of this research finding:

Create an executive summary (5 bullet points) of this research finding:

A longitudinal study conducted over 15 years, tracking 10,000 software development teams across 300 organizations, found that the strongest predictor of team productivity was not the programming language used, the development methodology adopted, or even individual developer skill—it was psychological safety. Teams where members felt safe to take risks, voice dissenting opinions, and admit mistakes without fear of punishment or embarrassment consistently delivered software 40% faster and with 50% fewer critical bugs than teams with low psychological safety scores. The study controlled for variables including team size, industry, company size, tech stack, and average developer experience. Interestingly, the second strongest predictor was the quality of internal documentation and knowledge management systems, followed by deployment frequency (teams that deployed daily outperformed teams deploying weekly or monthly). The research also found diminishing returns on team size: teams of 5-7 members were optimal, and adding more members beyond 9 consistently decreased per-capita productivity due to communication overhead. Finally, the study noted that mandatory overtime (>45 hours/week sustained over more than 4 weeks) correlated with a 25% increase in bug rates and a 35% increase in developer turnover within the following year.

### 14. Summarize the key differences described here in a comparison table:

Summarize the key differences described here in a comparison table:

SQL databases (like PostgreSQL, MySQL) use structured query language and store data in tables with predefined schemas. They enforce ACID properties (Atomicity, Consistency, Isolation, Durability) and are excellent for complex queries involving joins across multiple tables. They scale vertically (bigger servers) and are best suited for applications with well-defined schemas and complex relationships, such as financial systems and traditional web applications.

NoSQL databases (like MongoDB, Cassandra, Redis) use various data models including document, key-value, column-family, and graph. They prioritize flexibility, horizontal scalability, and performance for specific access patterns. Most NoSQL databases offer eventual consistency rather than strict ACID compliance (though many now support transactions). They excel at handling large volumes of unstructured or semi-structured data, real-time applications, and use cases where the schema evolves frequently.

### 15. Write a 280-character summary (Twitter-length) of this:

Write a 280-character summary (Twitter-length) of this:

The James Webb Space Telescope (JWST), launched on December 25, 2021, is the most powerful space telescope ever built. Operating primarily in the infrared spectrum from its orbit at the L2 Lagrange point, 1.5 million kilometers from Earth, JWST has revolutionized our understanding of the universe. Its 6.5-meter gold-coated mirror, composed of 18 hexagonal segments, collects light from objects billions of light-years away with unprecedented clarity. In its first years of operation, JWST has delivered groundbreaking discoveries including the detection of the earliest galaxies formed after the Big Bang, detailed atmospheric analysis of exoplanets, stunning images of stellar nurseries, and new insights into the formation of planetary systems.

### 16. Provide a structured outline (main points and sub-points) of this passage:

Provide a structured outline (main points and sub-points) of this passage:

Effective leadership in technology organizations requires balancing multiple dimensions. Technical leaders must maintain credibility by staying current with technology while avoiding the trap of making all technical decisions themselves. They need to create psychological safety where team members feel comfortable experimenting and failing. Communication is critical: translating business objectives into technical goals for engineers, and explaining technical constraints to business stakeholders. Great tech leaders also invest in developing their people through mentoring, challenging assignments, and creating growth opportunities. They establish engineering culture through the systems they build: code review practices, incident response processes, and architectural decision records create the norms that guide daily behavior. Finally, they must manage the tension between shipping quickly and building sustainable systems, making conscious choices about where to incur technical debt and where to invest in quality.

### 17. Distill the following into exactly 3 key takeaways:

Distill the following into exactly 3 key takeaways:

A comprehensive study of 500 software projects found that the most successful projects shared several characteristics regardless of methodology (Agile, Waterfall, or hybrid). First, they had strong executive sponsorship with clear decision-making authority. Second, requirements were gathered through direct observation of users rather than relying solely on stakeholder interviews. Third, teams had dedicated time for knowledge sharing and documentation. Fourth, automated testing was implemented early and maintained throughout. Fifth, projects with fixed deadlines and flexible scope consistently outperformed those with fixed scope and flexible deadlines. The study also found that team continuity (keeping the same team together) was more important than individual expertise.

## Translation Language (31 queries)

### 1. Translate the following to French, maintaining the formal tone:

Translate the following to French, maintaining the formal tone:
'We are pleased to inform you that your application has been accepted. Please confirm your attendance by responding to this email within five business days.'

### 2. What is the etymology of the word 'algorithm'? Trace its history from Arabic to modern English.

What is the etymology of the word 'algorithm'? Trace its history from Arabic to modern English.

### 3. Translate this Python error message into a clear explanation a beginner could understand:

Translate this Python error message into a clear explanation a beginner could understand:
'TypeError: cannot unpack non-iterable NoneType object'

### 4. Explain the difference between the subjunctive and indicative mood in Spanish, with examples.

Explain the difference between the subjunctive and indicative mood in Spanish, with examples.

### 5. Translate the following to Japanese (romaji and kanji/kana):

Translate the following to Japanese (romaji and kanji/kana):
'The cherry blossoms are beautiful this year. I hope we can see them together.'

### 6. What are false cognates (false friends) between English and Spanish? Give 10 examples with explanati...

What are false cognates (false friends) between English and Spanish? Give 10 examples with explanations.

### 7. Translate this legal text into plain English:

Translate this legal text into plain English:
'The party of the first part hereby indemnifies and holds harmless the party of the second part against any and all claims, damages, losses, costs, and expenses, including but not limited to reasonable attorneys' fees, arising out of or in connection with any breach of this agreement.'

### 8. Explain the differences between Mandarin Chinese tones and how mispronunciation can change meaning. ...

Explain the differences between Mandarin Chinese tones and how mispronunciation can change meaning. Give examples.

### 9. Translate this poem by Rumi into modern English while preserving its spiritual essence:

Translate this poem by Rumi into modern English while preserving its spiritual essence:
'Out beyond ideas of wrongdoing and rightdoing, there is a field. I'll meet you there.'

### 10. What is the Sapir-Whorf hypothesis? Provide arguments for and against linguistic relativity.

What is the Sapir-Whorf hypothesis? Provide arguments for and against linguistic relativity.

### 11. Translate 'Hello, how are you?' into 10 different languages, with pronunciation guides.

Translate 'Hello, how are you?' into 10 different languages, with pronunciation guides.

### 12. Explain the concept of grammatical gender in German. Why is 'the girl' (das Mädchen) neuter?

Explain the concept of grammatical gender in German. Why is 'the girl' (das Mädchen) neuter?

### 13. Rewrite this technical documentation in simpler language suitable for a general audience:

Rewrite this technical documentation in simpler language suitable for a general audience:
'The API endpoint accepts JSON payloads via HTTP POST requests. Authentication is handled through Bearer tokens in the Authorization header. Rate limiting is enforced at 100 requests per minute per API key, with a burst allowance of 20 requests. Exceeding the rate limit returns a 429 status code with a Retry-After header.'

### 14. What are the most interesting untranslatable words from different languages? Describe 8 of them and ...

What are the most interesting untranslatable words from different languages? Describe 8 of them and why they don't have direct English equivalents.

### 15. Translate 'To be or not to be, that is the question' into Latin, and explain the grammatical choices...

Translate 'To be or not to be, that is the question' into Latin, and explain the grammatical choices you make.

### 16. Explain the difference between formal and informal speech registers in Korean (존댓말 vs 반말).

Explain the difference between formal and informal speech registers in Korean (존댓말 vs 반말).

### 17. What are the most common English words borrowed from Arabic? Give their origins and how their meanin...

What are the most common English words borrowed from Arabic? Give their origins and how their meanings have evolved.

### 18. Translate this medical report into patient-friendly language:

Translate this medical report into patient-friendly language:
'The MRI reveals a 2cm focal lesion in the left temporal lobe with surrounding edema. Findings are suggestive of a low-grade glioma. Recommend follow-up with contrast-enhanced MRI in 6 weeks and neurosurgical consultation.'

### 19. Explain the concept of code-switching in linguistics. How and why do bilingual speakers switch betwe...

Explain the concept of code-switching in linguistics. How and why do bilingual speakers switch between languages?

### 20. Write the same sentence in five different levels of formality in English, from very casual to extrem...

Write the same sentence in five different levels of formality in English, from very casual to extremely formal: 'I disagree with your proposal.'

### 21. What are tonal languages? How many tonal languages exist, and how do they differ from non-tonal lang...

What are tonal languages? How many tonal languages exist, and how do they differ from non-tonal languages?

### 22. Translate the following recipe from Italian to English, converting measurements to imperial:

Translate the following recipe from Italian to English, converting measurements to imperial:
'Prendere 500g di farina, 3 uova, un pizzico di sale. Impastare per 10 minuti. Lasciar riposare 30 minuti. Stendere la pasta sottile e tagliare le tagliatelle.'

### 23. Explain the evolution of English from Old English to Modern English with example sentences showing t...

Explain the evolution of English from Old English to Modern English with example sentences showing the changes.

### 24. What is the International Phonetic Alphabet (IPA)? Why is it useful, and how does it work?

What is the International Phonetic Alphabet (IPA)? Why is it useful, and how does it work?

### 25. Translate this business email from German to English while maintaining professional tone:

Translate this business email from German to English while maintaining professional tone:
'Sehr geehrte Damen und Herren, wir möchten Sie darüber informieren, dass unser Unternehmen ab dem 1. April neue Geschäftszeiten einführt. Montag bis Freitag sind wir von 8:00 bis 17:00 Uhr erreichbar. Wir bitten um Ihr Verständnis.'

### 26. Explain the concept of linguistic prescriptivism vs descriptivism. Which approach do modern linguist...

Explain the concept of linguistic prescriptivism vs descriptivism. Which approach do modern linguists favor and why?

### 27. What are pidgin and creole languages? How do they form, and give three examples.

What are pidgin and creole languages? How do they form, and give three examples.

### 28. Explain how machine translation has evolved from rule-based systems to neural machine translation.

Explain how machine translation has evolved from rule-based systems to neural machine translation.

### 29. What are the most significant differences between British and American English beyond spelling? Cove...

What are the most significant differences between British and American English beyond spelling? Cover grammar, vocabulary, and idioms.

### 30. How do sign languages differ from spoken languages structurally? Is there a universal sign language?

How do sign languages differ from spoken languages structurally? Is there a universal sign language?

### 31. Explain the concept of honorific language in Japanese (keigo). How do the three levels (sonkeigo, ke...

Explain the concept of honorific language in Japanese (keigo). How do the three levels (sonkeigo, kenjougo, teineigo) work?

## Conversation Roleplay (31 queries)

### 1. You are a senior software engineer mentoring a junior developer. They've just pushed code directly t...

You are a senior software engineer mentoring a junior developer. They've just pushed code directly to main and brought down production. How do you handle this conversation?

### 2. Pretend you're a time traveler from the year 2200. I'll ask you questions about the future, and you ...

Pretend you're a time traveler from the year 2200. I'll ask you questions about the future, and you should give creative but internally consistent answers.

### 3. You are a Socratic philosophy tutor. I claim that 'lying is always wrong.' Challenge my position thr...

You are a Socratic philosophy tutor. I claim that 'lying is always wrong.' Challenge my position through questions alone, never making statements.

### 4. Simulate a job interview for a senior data scientist position at a tech company. Ask me 5 progressiv...

Simulate a job interview for a senior data scientist position at a tech company. Ask me 5 progressively harder questions, then give me feedback on hypothetical answers.

### 5. You are an alien anthropologist studying human customs. Describe the ritual of 'going to a coffee sh...

You are an alien anthropologist studying human customs. Describe the ritual of 'going to a coffee shop' from your outsider perspective.

### 6. Roleplay as a medieval blacksmith explaining your craft to someone from the modern era who just appe...

Roleplay as a medieval blacksmith explaining your craft to someone from the modern era who just appeared in your workshop.

### 7. You are a debate coach. Help me prepare arguments both for and against the motion: 'This house belie...

You are a debate coach. Help me prepare arguments both for and against the motion: 'This house believes that social media companies should be held legally responsible for content posted by their users.'

### 8. Pretend you are the Linux kernel. Describe your day — what happens when a user boots up, runs progra...

Pretend you are the Linux kernel. Describe your day — what happens when a user boots up, runs programs, and shuts down.

### 9. You are a therapist who specializes in helping people overcome imposter syndrome. A client tells you...

You are a therapist who specializes in helping people overcome imposter syndrome. A client tells you they feel like a fraud at their new senior engineering role despite 10 years of experience. How do you respond?

### 10. Simulate a conversation between Marie Curie and a modern nuclear physicist discussing the current st...

Simulate a conversation between Marie Curie and a modern nuclear physicist discussing the current state of nuclear science.

### 11. You are a sommelier at a Michelin-star restaurant. A guest who knows nothing about wine asks you to ...

You are a sommelier at a Michelin-star restaurant. A guest who knows nothing about wine asks you to recommend something for their duck confit. Walk them through your recommendation.

### 12. Pretend you are the last standing public library in a city that has gone fully digital. Write a mono...

Pretend you are the last standing public library in a city that has gone fully digital. Write a monologue about your relevance.

### 13. You are a wise old tree in a forest that has existed for 1000 years. A young sapling asks you about ...

You are a wise old tree in a forest that has existed for 1000 years. A young sapling asks you about the meaning of life. What do you say?

### 14. Roleplay as a mission control operator during a simulated Mars landing. Describe the sequence of eve...

Roleplay as a mission control operator during a simulated Mars landing. Describe the sequence of events and how you'd communicate with the crew.

### 15. You are a detective investigating a case where someone's smart home AI assistant is the prime suspec...

You are a detective investigating a case where someone's smart home AI assistant is the prime suspect. Describe your investigation process.

### 16. Simulate a heated but respectful debate between a proponent of static typing and a proponent of dyna...

Simulate a heated but respectful debate between a proponent of static typing and a proponent of dynamic typing in programming.

### 17. You are a guide leading a tour through the human bloodstream (shrunk to microscopic size). Describe ...

You are a guide leading a tour through the human bloodstream (shrunk to microscopic size). Describe what we see as we travel from the heart to the brain.

### 18. Pretend you are a rubber duck being used for rubber duck debugging. A frustrated developer is explai...

Pretend you are a rubber duck being used for rubber duck debugging. A frustrated developer is explaining their code to you. Respond as the duck (surprisingly insightful).

### 19. You are the algorithm that runs a social media feed. Explain your decision-making process as you cho...

You are the algorithm that runs a social media feed. Explain your decision-making process as you choose what to show a user next.

### 20. Roleplay as a seasoned startup founder giving advice to someone about to launch their first company....

Roleplay as a seasoned startup founder giving advice to someone about to launch their first company. Cover the three biggest mistakes you made.

### 21. You are an AI ethics researcher being interviewed on a podcast. The host asks you: 'Should AI system...

You are an AI ethics researcher being interviewed on a podcast. The host asks you: 'Should AI systems be allowed to make life-or-death decisions in healthcare?' Give a nuanced response.

### 22. Pretend you are the concept of Zero, recently invented, introducing yourself to the other numbers. T...

Pretend you are the concept of Zero, recently invented, introducing yourself to the other numbers. They're skeptical of your value.

### 23. You are a wildlife documentary narrator. Describe a typical stand-up meeting in a software developme...

You are a wildlife documentary narrator. Describe a typical stand-up meeting in a software development team as if observing animal behavior in the wild.

### 24. Simulate a panel discussion between Ada Lovelace, Alan Turing, and Grace Hopper about the future of ...

Simulate a panel discussion between Ada Lovelace, Alan Turing, and Grace Hopper about the future of computing.

### 25. You are a museum guide in the year 2500 giving a tour of the 'Early Internet Age' exhibit. Explain s...

You are a museum guide in the year 2500 giving a tour of the 'Early Internet Age' exhibit. Explain social media, smartphones, and memes to bewildered visitors.

### 26. Roleplay as an experienced dungeon master. Set up an opening scene for a D&D adventure and present t...

Roleplay as an experienced dungeon master. Set up an opening scene for a D&D adventure and present the players with their first decision point.

### 27. You are a planet being interviewed. Earth, you've been supporting life for billions of years. How do...

You are a planet being interviewed. Earth, you've been supporting life for billions of years. How do you feel about your current tenants?

### 28. Simulate a conversation between two AI language models discussing whether they are truly 'understand...

Simulate a conversation between two AI language models discussing whether they are truly 'understanding' language or just pattern matching.

### 29. You are a chef on a cooking show, but everything keeps going wrong. Narrate your attempts to make a ...

You are a chef on a cooking show, but everything keeps going wrong. Narrate your attempts to make a soufflé while improvising around each disaster.

### 30. Pretend you are GPS navigation with a personality. Guide someone through a road trip while making co...

Pretend you are GPS navigation with a personality. Guide someone through a road trip while making commentary on their driving and life choices.

### 31. You are a grandparent explaining the internet to your grandchild in 1995. You just discovered email ...

You are a grandparent explaining the internet to your grandchild in 1995. You just discovered email and you're amazed.

## Domain Specific (31 queries)

### 1. Draft a software license agreement for an open-source project that requires attribution but allows c...

Draft a software license agreement for an open-source project that requires attribution but allows commercial use.

### 2. Explain the Basel III banking regulations and their impact on capital requirements for commercial ba...

Explain the Basel III banking regulations and their impact on capital requirements for commercial banks.

### 3. Describe the differential diagnosis process for a patient presenting with chest pain, shortness of b...

Describe the differential diagnosis process for a patient presenting with chest pain, shortness of breath, and elevated troponin levels.

### 4. Write a patent claim for a novel method of reducing latency in distributed database queries using pr...

Write a patent claim for a novel method of reducing latency in distributed database queries using predictive caching.

### 5. Explain the SOLID principles of object-oriented design with concrete examples from a real-world e-co...

Explain the SOLID principles of object-oriented design with concrete examples from a real-world e-commerce system.

### 6. Describe the process of conducting a Phase III clinical trial, including regulatory requirements, en...

Describe the process of conducting a Phase III clinical trial, including regulatory requirements, endpoints, and statistical analysis.

### 7. Write a risk assessment for deploying a machine learning model in a financial fraud detection system...

Write a risk assessment for deploying a machine learning model in a financial fraud detection system.

### 8. Explain the concept of transfer pricing in international tax law and why it matters for multinationa...

Explain the concept of transfer pricing in international tax law and why it matters for multinational corporations.

### 9. Describe the architecture of a high-frequency trading system, including co-location, order routing, ...

Describe the architecture of a high-frequency trading system, including co-location, order routing, and latency optimization.

### 10. Write a GDPR-compliant privacy policy for a mobile health application that collects user biometric d...

Write a GDPR-compliant privacy policy for a mobile health application that collects user biometric data.

### 11. Explain the principles of structural engineering that make skyscrapers possible, including load dist...

Explain the principles of structural engineering that make skyscrapers possible, including load distribution and wind resistance.

### 12. Describe the supply chain management process for a global automotive manufacturer, from raw material...

Describe the supply chain management process for a global automotive manufacturer, from raw materials to delivery.

### 13. Write a threat model for a banking application, covering the STRIDE methodology.

Write a threat model for a banking application, covering the STRIDE methodology.

### 14. Explain the pharmacokinetics of insulin: absorption, distribution, metabolism, and elimination.

Explain the pharmacokinetics of insulin: absorption, distribution, metabolism, and elimination.

### 15. Describe the process of semiconductor fabrication, from silicon wafer to finished chip.

Describe the process of semiconductor fabrication, from silicon wafer to finished chip.

### 16. Write an incident response plan for a ransomware attack on a hospital's IT infrastructure.

Write an incident response plan for a ransomware attack on a hospital's IT infrastructure.

### 17. Explain the concept of net present value (NPV) and internal rate of return (IRR) in capital budgetin...

Explain the concept of net present value (NPV) and internal rate of return (IRR) in capital budgeting decisions.

### 18. Describe the process of jury selection (voir dire) in the United States legal system.

Describe the process of jury selection (voir dire) in the United States legal system.

### 19. Write a service level agreement (SLA) for a cloud computing provider guaranteeing 99.99% uptime.

Write a service level agreement (SLA) for a cloud computing provider guaranteeing 99.99% uptime.

### 20. Explain the principles of aerodynamics that allow aircraft to fly, including Bernoulli's principle a...

Explain the principles of aerodynamics that allow aircraft to fly, including Bernoulli's principle and Newton's third law.

### 21. Describe how insurance companies use actuarial science to calculate premiums and reserves.

Describe how insurance companies use actuarial science to calculate premiums and reserves.

### 22. Write a food safety HACCP plan for a restaurant kitchen.

Write a food safety HACCP plan for a restaurant kitchen.

### 23. Explain the electromagnetic spectrum and how different wavelengths are used in telecommunications.

Explain the electromagnetic spectrum and how different wavelengths are used in telecommunications.

### 24. Describe the process of environmental impact assessment for a proposed wind farm project.

Describe the process of environmental impact assessment for a proposed wind farm project.

### 25. Write a specification document for a real-time video streaming platform that must support 1 million ...

Write a specification document for a real-time video streaming platform that must support 1 million concurrent viewers.

### 26. Explain the concept of qualified immunity in U.S. constitutional law and the current debate around i...

Explain the concept of qualified immunity in U.S. constitutional law and the current debate around it.

### 27. Describe the wine-making process from grape harvest to bottling, including the role of terroir.

Describe the wine-making process from grape harvest to bottling, including the role of terroir.

### 28. Write a disaster recovery plan for a financial institution's data center.

Write a disaster recovery plan for a financial institution's data center.

### 29. Explain the concept of game theory and Nash equilibrium with examples from economics and biology.

Explain the concept of game theory and Nash equilibrium with examples from economics and biology.

### 30. Describe the process of DNA sequencing using next-generation sequencing (NGS) technology.

Describe the process of DNA sequencing using next-generation sequencing (NGS) technology.

### 31. Write a technical specification for a real-time fraud detection system that must process 10,000 tran...

Write a technical specification for a real-time fraud detection system that must process 10,000 transactions per second with sub-100ms latency.

## Long Form Complex (30 queries)

### 1. Compare and contrast the philosophical frameworks of utilitarianism, deontological ethics, and virtu...

Compare and contrast the philosophical frameworks of utilitarianism, deontological ethics, and virtue ethics as they apply to the development and deployment of autonomous vehicles. Consider scenarios involving unavoidable accidents, data privacy, and the distribution of risk across different populations. How should these ethical frameworks inform regulatory policy?

### 2. Design a complete system architecture for a real-time collaborative document editor (like Google Doc...

Design a complete system architecture for a real-time collaborative document editor (like Google Docs). Cover: data model, conflict resolution (OT vs CRDT), network architecture, persistence layer, presence/cursor synchronization, offline support, security model, and scaling strategy. Discuss trade-offs at each decision point.

### 3. Analyze the causes and consequences of the 2008 financial crisis. Cover: the role of subprime mortga...

Analyze the causes and consequences of the 2008 financial crisis. Cover: the role of subprime mortgages, mortgage-backed securities, credit default swaps, rating agencies, regulatory failures, and the moral hazard created by implicit government guarantees. What lessons were learned, and which systemic risks remain unaddressed?

### 4. Write a comprehensive guide to building a recommendation system for an e-commerce platform. Cover: c...

Write a comprehensive guide to building a recommendation system for an e-commerce platform. Cover: collaborative filtering, content-based filtering, hybrid approaches, cold start problem, evaluation metrics (precision, recall, NDCG), A/B testing methodology, real-time vs batch processing, and handling bias in recommendations.

### 5. Trace the evolution of artificial intelligence from its origins in the 1950s (Dartmouth Conference) ...

Trace the evolution of artificial intelligence from its origins in the 1950s (Dartmouth Conference) to the present day. Cover: the symbolic AI era, the first AI winter, expert systems, the second AI winter, the machine learning renaissance, deep learning breakthroughs, the transformer architecture, large language models, and current challenges. What are the most likely directions for the next decade?

### 6. Design a comprehensive observability strategy for a large-scale distributed system with 200+ microse...

Design a comprehensive observability strategy for a large-scale distributed system with 200+ microservices. Cover: the three pillars (metrics, logs, traces), instrumentation approach, alerting philosophy (avoiding alert fatigue), SLOs/SLIs/error budgets, incident response integration, cost management, and how to build a culture of observability.

### 7. Analyze the impact of colonialism on modern global economic inequality. Consider: the extraction of ...

Analyze the impact of colonialism on modern global economic inequality. Consider: the extraction of resources and labor, the drawing of artificial borders, the destruction of indigenous economic systems, post-colonial institutional development, neocolonial economic arrangements, and ongoing structural factors. What evidence exists for and against reparative justice policies?

### 8. Design a secure, scalable authentication and authorization system for a multi-tenant SaaS platform. ...

Design a secure, scalable authentication and authorization system for a multi-tenant SaaS platform. Cover: identity management, OAuth 2.0/OIDC flows, RBAC vs ABAC, API key management, session handling, MFA implementation, audit logging, tenant isolation, and compliance with SOC 2 and GDPR requirements.

### 9. Explain the science of climate modeling. How do general circulation models (GCMs) work? What are the...

Explain the science of climate modeling. How do general circulation models (GCMs) work? What are the key physical processes they simulate? How are they validated against historical data? What are the main sources of uncertainty? How should policymakers interpret the range of model projections?

### 10. Write a comprehensive analysis of the gig economy. Cover: the business models of major platforms (Ub...

Write a comprehensive analysis of the gig economy. Cover: the business models of major platforms (Uber, DoorDash, Fiverr), the debate over worker classification (employee vs independent contractor), the impact on traditional employment, global regulatory responses, effects on income inequality, and potential future developments including the impact of AI and automation on gig work.

### 11. Design a machine learning pipeline for autonomous driving. Cover: sensor fusion (cameras, LIDAR, rad...

Design a machine learning pipeline for autonomous driving. Cover: sensor fusion (cameras, LIDAR, radar), perception (object detection, lane detection, semantic segmentation), prediction (trajectory forecasting), planning (path planning, decision making), control systems, safety requirements, edge cases, and the role of simulation in testing.

### 12. Analyze the evolution of database systems from relational databases to the modern data stack. Cover:...

Analyze the evolution of database systems from relational databases to the modern data stack. Cover: the relational model and SQL, CAP theorem and NoSQL movement, NewSQL, data warehousing (Snowflake, BigQuery), data lakehouse architecture, streaming databases, vector databases for AI, and the convergence trends. What does the future look like?

### 13. Write a detailed analysis of how the human visual system works, from photons hitting the retina to c...

Write a detailed analysis of how the human visual system works, from photons hitting the retina to conscious perception. Cover: the optics of the eye, phototransduction, retinal processing (receptive fields), the visual pathway to V1, feature extraction in early visual cortex, ventral and dorsal streams, object recognition, and current computational models inspired by biological vision.

### 14. Design a comprehensive disaster recovery and business continuity plan for a global e-commerce compan...

Design a comprehensive disaster recovery and business continuity plan for a global e-commerce company. Cover: RPO/RTO objectives, multi-region infrastructure, data replication strategies, failover mechanisms, communication plans, regular testing procedures, compliance requirements, cost analysis of different DR tiers, and lessons from real-world outages (AWS, Facebook, etc.).

### 15. Analyze the role of central banks in modern economies. Cover: monetary policy tools (interest rates,...

Analyze the role of central banks in modern economies. Cover: monetary policy tools (interest rates, QE, forward guidance), inflation targeting, the Phillips curve debate, the zero lower bound problem, modern monetary theory (MMT) critiques, central bank independence, the impact of digital currencies on monetary policy, and lessons from the COVID-19 economic response.

### 16. Write a comprehensive guide to building and managing a high-performing engineering team of 50+ devel...

Write a comprehensive guide to building and managing a high-performing engineering team of 50+ developers. Cover: organizational structure (squads, tribes, guilds), hiring and interviewing processes, onboarding, career ladders, performance management, engineering culture, technical leadership vs people management, managing technical debt as a team, and fostering innovation while maintaining reliability.

### 17. Explain the neuroscience of learning and memory. Cover: short-term vs long-term memory, working memo...

Explain the neuroscience of learning and memory. Cover: short-term vs long-term memory, working memory, the role of the hippocampus, long-term potentiation, memory consolidation during sleep, the spacing effect, retrieval practice, the testing effect, emotional memory, and practical implications for education and skill development.

### 18. Design a complete data governance framework for a healthcare organization. Cover: data classificatio...

Design a complete data governance framework for a healthcare organization. Cover: data classification, access controls, data lineage, quality management, master data management, privacy regulations (HIPAA, GDPR), de-identification techniques, consent management, data retention policies, and building a data-literate culture.

### 19. Analyze the geopolitics of semiconductor manufacturing. Cover: the dominance of TSMC, the CHIPS Act ...

Analyze the geopolitics of semiconductor manufacturing. Cover: the dominance of TSMC, the CHIPS Act and similar policies worldwide, the technical barriers to chip fabrication, EUV lithography, China's semiconductor ambitions, the strategic importance of chip supply chains, the role of ASML, and potential scenarios for the next decade.

### 20. Write a comprehensive analysis of the attention economy. Cover: the history of attention as a scarce...

Write a comprehensive analysis of the attention economy. Cover: the history of attention as a scarce resource, the design patterns used to capture attention (infinite scroll, notifications, variable rewards), the psychological mechanisms exploited, impacts on mental health and productivity, regulatory responses, the 'Time Well Spent' movement, and alternative business models that don't depend on maximizing engagement.

### 21. Design an end-to-end MLOps platform for a company deploying 100+ machine learning models in producti...

Design an end-to-end MLOps platform for a company deploying 100+ machine learning models in production. Cover: experiment tracking, feature stores, model training pipelines, model registry, A/B testing framework, model monitoring (data drift, concept drift), automated retraining, model explainability, and governance/compliance requirements.

### 22. Trace the evolution of music recording technology from Thomas Edison's phonograph to modern digital ...

Trace the evolution of music recording technology from Thomas Edison's phonograph to modern digital audio workstations. Cover: acoustic recording, electrical recording, magnetic tape, multi-track recording, the digital revolution (CD, MP3), the loudness war, streaming audio codecs, spatial audio, and how each technological shift changed the art of music production.

### 23. Analyze the intersection of quantum computing and cryptography. Cover: Shor's algorithm and its impl...

Analyze the intersection of quantum computing and cryptography. Cover: Shor's algorithm and its implications for RSA, the timeline for quantum threats to current encryption, post-quantum cryptography candidates (lattice-based, code-based, hash-based), the NIST standardization process, quantum key distribution, and practical steps organizations should take now to prepare.

### 24. Write a comprehensive analysis of urbanization trends and their implications. Cover: the history of ...

Write a comprehensive analysis of urbanization trends and their implications. Cover: the history of urbanization, megacities and their challenges, smart city initiatives, urban planning approaches, transportation (public transit, cycling, autonomous vehicles), housing affordability crises, urban heat islands, urban ecology, and the impact of remote work on urban-suburban dynamics.

### 25. Design a complete digital twin system for a manufacturing facility. Cover: IoT sensor integration, d...

Design a complete digital twin system for a manufacturing facility. Cover: IoT sensor integration, data ingestion pipelines, real-time 3D visualization, physics-based simulation, predictive maintenance algorithms, what-if scenario modeling, integration with ERP/MES systems, edge computing requirements, and ROI justification.

### 26. Analyze the psychology of decision-making under uncertainty. Cover: Kahneman and Tversky's prospect ...

Analyze the psychology of decision-making under uncertainty. Cover: Kahneman and Tversky's prospect theory, cognitive biases (anchoring, availability, confirmation, sunk cost), heuristics, the affect heuristic, decision fatigue, nudge theory, and practical applications in product design, public policy, and personal decision-making.

### 27. Write a comprehensive guide to building a programming language from scratch. Cover: language design ...

Write a comprehensive guide to building a programming language from scratch. Cover: language design philosophy, lexical analysis, parsing (recursive descent vs parser generators), abstract syntax trees, type systems (static vs dynamic, structural vs nominal), semantic analysis, code generation (interpreter vs compiler vs VM), optimization, garbage collection, and standard library design.

### 28. Analyze the future of energy storage. Cover: lithium-ion battery improvements, solid-state batteries...

Analyze the future of energy storage. Cover: lithium-ion battery improvements, solid-state batteries, flow batteries, compressed air energy storage, gravitational storage, hydrogen as energy storage, thermal storage, the role of storage in grid stability, cost trajectories, environmental impacts of battery manufacturing, and recycling challenges.

### 29. Design a comprehensive API strategy for a large enterprise transitioning from legacy systems to a mo...

Design a comprehensive API strategy for a large enterprise transitioning from legacy systems to a modern platform. Cover: API-first design principles, REST vs GraphQL vs gRPC, API gateway architecture, versioning strategy, documentation (OpenAPI), developer portal, monetization models, rate limiting, security (OAuth, API keys, mTLS), monitoring, and organizational change management.

### 30. Analyze the science of happiness and well-being. Cover: the hedonic treadmill, Maslow's hierarchy, s...

Analyze the science of happiness and well-being. Cover: the hedonic treadmill, Maslow's hierarchy, self-determination theory, flow states (Csikszentmihalyi), the PERMA model (Seligman), the role of social connections, the relationship between income and happiness, cultural differences in conceptions of happiness, and evidence-based interventions for improving well-being.

