import { serve } from "https://deno.land/std@0.168.0/http/server.ts"
import { createClient } from 'https://esm.sh/@supabase/supabase-js@2'
import OpenAI from 'https://esm.sh/openai@4.28.0'

const openai = new OpenAI({ apiKey: Deno.env.get('OPENAI_API_KEY') })
const supabase = createClient(
    Deno.env.get('SUPABASE_URL')!,
    Deno.env.get('SUPABASE_SERVICE_ROLE_KEY')!
)

const USER_ID = 1;

// --- LAS MISMAS HERRAMIENTAS DE ANTES ---
const tools = [
    {
        type: "function",
        function: {
            name: "consultar_saldo",
            description: "Devuelve el saldo actual.",
            parameters: { type: "object", properties: {} }
        }
    },
    {
        type: "function",
        function: {
            name: "consultar_meta",
            description: "Devuelve el monto objetivo y cuánto falta.",
            parameters: { type: "object", properties: {} }
        }
    },
    {
        type: "function",
        function: {
            name: "dame_consejo",
            description: "Da un consejo financiero basado en gastos.",
            parameters: { type: "object", properties: {} }
        }
    }
];

serve(async (req) => {
    try {
        // 1. RECIBIR EL AUDIO (Input del usuario)
        const formData = await req.formData()
        const audioFile = formData.get('file') // El archivo debe llamarse 'file'

        if (!audioFile) {
            return new Response("No se envió archivo de audio", { status: 400 })
        }

        // 2. WHISPER: Audio -> Texto
        console.log("👂 Escuchando...")
        const transcription = await openai.audio.transcriptions.create({
            file: audioFile,
            model: "whisper-1",
            language: "es" // Forzamos español para mejor precisión
        });

        const preguntaTexto = transcription.text;
        console.log("Usuario dijo:", preguntaTexto);

        // 3. GPT + SUPABASE: Pensar y Consultar DB
        // (Esta es la misma lógica de antes, resumida)
        const completion = await openai.chat.completions.create({
            model: "gpt-4-turbo",
            messages: [
                { role: "system", content: "Eres un asistente de voz financiero. Tus respuestas deben ser breves, habladas y naturales." },
                { role: "user", content: preguntaTexto }
            ],
            tools: tools,
            tool_choice: "auto",
        });

        const msg = completion.choices[0].message;
        let respuestaFinal = msg.content; // Si no usa herramientas, responde directo

        // Si GPT quiere usar herramientas (DB)
        if (msg.tool_calls) {
            const toolCall = msg.tool_calls[0];
            const fnName = toolCall.function.name;
            let dbData = "";

            if (fnName === "consultar_saldo") {
                const { data } = await supabase.from('cuentas').select('saldo_actual').eq('id', USER_ID).single();
                dbData = JSON.stringify(data);
            }
            else if (fnName === "consultar_meta") {
                const { data } = await supabase.from('cuentas').select('saldo_actual, meta').eq('id', USER_ID).single();
                const falta = data.meta - data.saldo_actual;
                dbData = JSON.stringify({ meta: data.meta, actual: data.saldo_actual, falta });
            }
            else if (fnName === "dame_consejo") {
                const movs = await supabase.from('movimientos').select('tipo, monto, descripcion').eq('cuenta_id', USER_ID).limit(5);
                dbData = JSON.stringify(movs.data);
            }

            // Segunda vuelta a GPT con los datos
            const secondResponse = await openai.chat.completions.create({
                model: "gpt-4-turbo",
                messages: [
                    { role: "system", content: "Responde brevemente para ser escuchado." },
                    { role: "user", content: preguntaTexto },
                    msg,
                    { role: "tool", tool_call_id: toolCall.id, content: dbData }
                ]
            });
            respuestaFinal = secondResponse.choices[0].message.content;
        }

        console.log("🤖 Respuesta texto:", respuestaFinal);

        // 4. TTS: Texto -> Audio (Output del sistema)
        console.log("🗣️ Hablando...")
        const mp3 = await openai.audio.speech.create({
            model: "tts-1",
            voice: "alloy", // Voces disponibles: alloy, echo, fable, onyx, nova, shimmer
            input: respuestaFinal,
        });

        // Convertimos a buffer para enviar
        const buffer = new Uint8Array(await mp3.arrayBuffer());

        // 5. RESPONDER CON AUDIO
        return new Response(buffer, {
            headers: {
                "Content-Type": "audio/mpeg",
                "Content-Length": buffer.length.toString()
            },
        });

    } catch (error) {
        return new Response(JSON.stringify({ error: error.message }), { status: 500 })
    }
})