import { serve } from "https://deno.land/std@0.168.0/http/server.ts"
import { createClient } from 'https://esm.sh/@supabase/supabase-js@2'
import OpenAI from 'https://esm.sh/openai@4.28.0'

// Clientes (Sin seguridad compleja, directo al grano)
const openai = new OpenAI({ apiKey: Deno.env.get('OPENAI_API_KEY') })
const supabase = createClient(
    Deno.env.get('SUPABASE_URL')!,
    Deno.env.get('SUPABASE_SERVICE_ROLE_KEY')! // Permiso total para leer tu DB
)

// ID de usuario fijo para este ejemplo (el usuario "1")
const USER_ID = 1;

// --- A. DEFINIMOS LAS 3 HERRAMIENTAS PARA GPT ---
const tools = [
    {
        type: "function",
        function: {
            name: "consultar_saldo",
            description: "Devuelve el saldo actual disponible en la cuenta.",
            parameters: { type: "object", properties: {} }
        }
    },
    {
        type: "function",
        function: {
            name: "consultar_meta",
            description: "Devuelve el monto objetivo de ahorro (meta) y calcula cuánto falta.",
            parameters: { type: "object", properties: {} }
        }
    },
    {
        type: "function",
        function: {
            name: "dame_consejo",
            description: "Analiza gastos recientes y da un consejo financiero breve.",
            parameters: { type: "object", properties: {} }
        }
    }
];

serve(async (req) => {
    try {
        // 1. Recibimos la pregunta del usuario (texto)
        const { pregunta } = await req.json()

        // 2. Primer viaje a GPT: "¿Qué herramienta uso?"
        const completion = await openai.chat.completions.create({
            model: "gpt-4-turbo",
            messages: [
                { role: "system", content: "Eres un asistente financiero útil." },
                { role: "user", content: pregunta }
            ],
            tools: tools,
            tool_choice: "auto", // GPT decide si usa herramienta o habla normal
        });

        const msg = completion.choices[0].message;

        // 3. SI GPT DECIDE USAR UNA HERRAMIENTA...
        if (msg.tool_calls) {
            const toolCall = msg.tool_calls[0];
            const fnName = toolCall.function.name;

            let resultadoParaGPT = "";

            // --- ENRUTAMIENTO (Tus 3 acciones) ---

            // CASO 1: SALDO
            if (fnName === "consultar_saldo") {
                const { data } = await supabase.from('cuentas').select('saldo_actual').eq('id', USER_ID).single();
                resultadoParaGPT = JSON.stringify(data); // Ej: { "saldo_actual": 24098 }
            }

            // CASO 2: META (Usando tu columna 'meta' en 'cuentas')
            else if (fnName === "consultar_meta") {
                const { data } = await supabase.from('cuentas').select('saldo_actual, meta').eq('id', USER_ID).single();
                // Calculamos la diferencia aquí para ayudar a GPT
                const falta = data.meta - data.saldo_actual;
                resultadoParaGPT = JSON.stringify({ meta: data.meta, actual: data.saldo_actual, falta: falta });
            }

            // CASO 3: CONSEJO (Requiere leer movimientos)
            else if (fnName === "dame_consejo") {
                // Leemos saldo, meta y últimos 5 movimientos
                const cuenta = await supabase.from('cuentas').select('saldo_actual, meta').eq('id', USER_ID).single();
                const movs = await supabase.from('movimientos')
                    .select('tipo, monto, descripcion')
                    .eq('cuenta_id', USER_ID)
                    .order('created_at', { ascending: false })
                    .limit(5);

                resultadoParaGPT = JSON.stringify({ contexto_cuenta: cuenta.data, ultimos_gastos: movs.data });
            }

            // 4. Segundo viaje a GPT: "Aquí tienes los datos, responde al usuario"
            const secondResponse = await openai.chat.completions.create({
                model: "gpt-4-turbo",
                messages: [
                    { role: "system", content: "Eres un analista financiero. Responde de forma directa basándote en los datos." },
                    { role: "user", content: pregunta },
                    msg, // Historial: "Quise llamar a tal función"
                    {
                        role: "tool",
                        tool_call_id: toolCall.id,
                        content: resultadoParaGPT // Los datos reales de tu DB
                    }
                ]
            });

            return new Response(JSON.stringify({ respuesta: secondResponse.choices[0].message.content }), { headers: { "Content-Type": "application/json" } });
        }

        // Si no usó herramientas (ej: "Hola"), responde directo
        return new Response(JSON.stringify({ respuesta: msg.content }), { headers: { "Content-Type": "application/json" } });

    } catch (error) {
        return new Response(JSON.stringify({ error: error.message }), { status: 500 })
    }
})
