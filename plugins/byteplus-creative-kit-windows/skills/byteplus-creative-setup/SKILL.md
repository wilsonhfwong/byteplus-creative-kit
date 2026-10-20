---
name: byteplus-creative-setup
description: Set up or update the local BytePlus Creative Kit plugin without a terminal. Use after installation, for missing credentials, or to change the BytePlus account, bucket, project or optional Seed text model.
---

Call `creative_kit_status` to check local configuration. For first use or requested credential changes, call `creative_kit_setup`. It opens a private browser form on the user's computer. If it cannot open automatically, show the returned local link. Tell the user to enter credentials there and save; never ask them to paste API keys, IAM keys or session tokens into chat. Do not read, display or collect the settings file's secrets yourself.

After the user saves, call `creative_kit_status`. If runtime is `preparing`, poll about every 10 seconds while continuing the conversation, until `ready` or `failed`. Preparing runtime does not submit a cloud task. If it fails, report that the local setup needs attention and ask the user to reopen the form to retry after checking network access. Do not direct a nontechnical customer to run Terminal, CMD, Python or Docker.

API Key alone enables generation. Asset management also needs IAM AK/SK; importing local files needs a private TOS bucket in ap-southeast-1. Optional Seed text needs a model/Endpoint ID. These should be entered only into the form. Setup does not create buckets, enable account services or call billed generation.

When ready, explain that outputs save to the Downloads/BytePlus Creative Kit folder. Continue with the user's requested creation; if they only asked for installation, report setup complete without starting paid generation.
