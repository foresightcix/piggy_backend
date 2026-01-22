import { writeFileSync } from "node:fs";
import OpenAI from "openai";
import dotenv from "dotenv";

// Load environment variables from .env file
dotenv.config();

const openai = new OpenAI({
    apiKey: process.env.OPENAI_API_KEY,
});

// Generate an audio response to the given prompt
const response = await openai.chat.completions.create({
    model: "gpt-audio",
    modalities: ["text", "audio"],
    audio: { voice: "alloy", format: "wav" },
    messages: [
        {
            role: "user",
            content: "dame algunos datos curiosos de lima"
        }
    ],
    store: true,
});

// Inspect returned data
console.log(response.choices[0]);

// Write audio data to a file
writeFileSync(
    "dog.wav",
    Buffer.from(response.choices[0].message.audio.data, 'base64'),
    { encoding: "utf-8" }
);