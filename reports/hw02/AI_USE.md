1) what you used an AI assistant for and what
you did yourself
AI was used in this assignment to debug code and as a guide to help me look up resources on what to use in the code

2) one AI-produced output that was wrong/unsuitable, or one thing
you independently verified
When I was working on FastAPI and connecting it to the HTML and JavaScript files, I placed the HTML and JavaScript inside the "static" folder. While debugging, AI indicated that the original code without indicating the existence of the "static" folder was fine.

3) how you detected the problem or verified the result
I eventually figured out the issue by seeing a 404 error in the terminal while running and testing my website.

4) what you changed and why it works now.
What was originally return FileResponse("HW1 - Angela Wei.html") in my FastAPI file is now return FileResponse("static/HW1 - Angela Wei.html"),
What was originally <script src = "HW1 - Angela Wei.js"> in my HTML is now </script><script src = "/static/HW1 - Angela Wei.js"></script>