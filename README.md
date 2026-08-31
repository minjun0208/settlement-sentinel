\# Settlement Sentinel



A background agent, built with the AWS Strands Agents SDK, that reconciles

delivery-platform settlement statements for a small restaurant business.

It files disputes when the evidence is certain and \*\*refuses to act\*\* when

it is not, escalating to the owner with a one-line question instead.



Built for the AWS \*\*Agents for Humans\*\* hackathon, Professional Agents track.

All code written during the submission period. Synthetic data only.



\## Quick start



```bash

pip install -r requirements.txt

cp .env.example .env   # add your Amazon Bedrock API key (us-west-2)

python agent.py baemin

python agent.py yogiyo

python agent.py pending

python agent.py approve YG-3005 confirmed double deduction

```



\## Design in one line



The LLM orchestrates; it never touches a number.



Full README, architecture diagram and demo video to follow.

