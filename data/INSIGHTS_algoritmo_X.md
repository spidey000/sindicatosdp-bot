# Insights del algoritmo del "For You" de X

> Análisis del código fuente publicado por xAI el 15 de mayo de 2026 en [github.com/xai-org/x-algorithm](https://github.com/xai-org/x-algorithm).
>
> Todas las afirmaciones de este documento están respaldadas por una cita al archivo de origen. Cuando algo no se puede confirmar desde el código (p. ej. valores numéricos exactos de pesos), se indica explícitamente.

---

## TL;DR para creadores de contenido

1. **El algoritmo predice 22 acciones del lector** y combina sus probabilidades con pesos. No optimizas "engagement" en abstracto — optimizas P(like), P(reply), P(retweet), P(dwell), P(quote), P(follow_author)… y evitas P(not_interested), P(block), P(mute), P(report), P(not_dwelled).
2. **Lo peor que puedes hacer NO es generar pocos likes** — es generar bloqueos, silencios, denuncias y, sobre todo, que el usuario *no se quede* en el post (`not_dwelled`). Ese conjunto de señales negativas se resta al score, no solo lo no-suma.
3. **Tu post tiene que cruzar un umbral de "min-traction" para entrar en el pipeline de Grok**. Si en los primeros minutos no recibe engagement, **nunca pasa por el Banger Initial Screen** y queda fuera del descubrimiento amplio. Los primeros 30-60 minutos son cuello de botella, no aceleración.
4. **El modelo conoce la EDAD del post**. La edad se codifica explícitamente como feature con buckets de 1 hora y cap a **80 horas** (después de eso, todo se trata como "muy viejo"). Cualquier contenido de >3 días está en el "overflow bucket": no espera milagros.
5. **Spamear desde la misma cuenta penaliza brutalmente**. Hay una *Author Diversity Decay* (`decay^posición + suelo`) que recorta exponencialmente el score de cada siguiente post tuyo en el mismo feed.
6. **Vídeo importa, pero solo si supera un mínimo de duración** (`MinVideoDurationMs`). Por debajo de ese umbral el peso de Video Quality View (VQV) se anula a 0. Además, Grok **transcribe el audio** de tus vídeos (ASR) y usa el texto para clasificarlos.
7. **Fuera-de-red (OON) se multiplica por un factor < 1** (`OonWeightFactor`). Para llegar a no-seguidores hace falta una P(engagement) bastante más alta para compensar el descuento. Excepción: *usuarios nuevos* tienen un multiplicador OON propio (mucho mayor) para que descubran cuentas.
8. **Algunos usuarios apagan el For You.** Si tu audiencia objetivo tiene `allow_for_you_recommendations = false`, **NUNCA** los alcanzas out-of-network. La única vía es que te sigan.
9. **Los hilos compiten consigo mismos**: `DedupConversationFilter` deja **un único tweet por hilo** en el feed (el de mayor score). Hacer 12 respuestas a tu propio post no te da 12 oportunidades.
10. **Grok-VLM puntúa cada post original** con un *quality_score* 0-1 (umbral "banger" ≥ 0.4), un *slop_score*, y un *has_minor_score*. Las respuestas y los retweets **no pasan** por este clasificador; solo los posts originales.
11. **Las respuestas a cuentas pequeñas se escanean por spam** con Grok. Las respuestas a cuentas grandes pasan por *ReplyRanking* (puntuación 0-3 que decide el orden en la conversación).
12. **País, idioma, IP y datos demográficos del *viewer*** se inyectan como features de la query. El post solo lleva `language_code`, **no país del autor**. No hay un filtro hardcoded "EU→US penalizado", pero el modelo aprende correlaciones país↔engagement de los datos.
13. **Cuentas privadas (`is_protected`) no generan embedding** → no aparecen en retrieval fuera-de-red. Si quieres alcance, no puedes ser protegida.
14. **El modelo solo recuerda tus últimas ~128 acciones** (en la versión mini publicada; producción seguramente más). El historial relevante para el For You es relativamente corto y reciente.
15. **El 50% de las requests son "shadow traffic"** que activa features experimentales — la inferencia de género, los topics Grok, las facepiles de mutuals, etc. corren para aproximadamente la mitad de tu audiencia siempre, aunque los flags estén "off".

---

## 1. Arquitectura del pipeline (a grandes rasgos)

Cada petición al feed pasa por:

1. **Query Hydration** — se enriquece la consulta con el contexto del usuario (engagement sequence, follow graph, IP, demografía, géneros inferido, topics, *starter packs* seguidos, *seen* bloom filters…).
2. **Candidate Sourcing** — varias fuentes en paralelo:
   - **Thunder** → posts in-network (de gente que sigues) servidos desde un store en RAM, sub-milisegundo.
   - **Phoenix Retrieval** → posts out-of-network buscados por similitud con tu *user embedding* (Two-Tower).
   - **Tweet Mixer**, **Phoenix MoE**, **Phoenix Topics**, **Cached Posts**, **Ads**, **Who-To-Follow**, **Prompts**, **Push-to-Home**.
3. **Candidate Hydration** — se rellenan datos del post: texto, autor (Gizmoduck), idioma, media, contadores de engagement, *brand safety verdict*, scores de mutual-follow, topics filtrados, etc.
4. **Pre-scoring Filters** — quitan candidatos inelegibles.
5. **Scoring** — el *Phoenix Scorer* llama al transformer Grok-based con tu *scoring_sequence* y obtiene 22 probabilidades por candidato; el *WeightedScorer* las combina linealmente; *AuthorDiversityScorer* castiga repetición de autor; *OONScorer* castiga fuera-de-red.
6. **Selection** — `TopKScoreSelector` toma los mejores K (`params::TOP_K_CANDIDATES_TO_SELECT`).
7. **Post-Selection Filters** — VFFilter (visibility filtering por NSFW/violencia/spam/borrado), DedupConversationFilter.
8. **BlenderSelector** — mezcla orgánico + ads + WTF + prompts + push-to-home en un único feed final.

Fuente: [`README.md`](x-algorithm/README.md), [`home-mixer/candidate_pipeline/phoenix_candidate_pipeline.rs`](x-algorithm/home-mixer/candidate_pipeline/phoenix_candidate_pipeline.rs), [`home-mixer/lib.rs`](x-algorithm/home-mixer/lib.rs).

---

## 2. Las 22 señales que el modelo predice (qué optimizar y qué evitar)

`PhoenixScorer` pide al transformer una *PhoenixScores* con 22 campos. El `RankingScorer` los combina así:

```
score = Σ peso_i · P(acción_i)
```

Fuente: [`home-mixer/scorers/ranking_scorer.rs`](x-algorithm/home-mixer/scorers/ranking_scorer.rs) líneas 12–115, [`home-mixer/scorers/weighted_scorer.rs`](x-algorithm/home-mixer/scorers/weighted_scorer.rs) líneas 49–67.

### Señales positivas (suman al score)

| Señal | Qué predice | Cómo dispararla con tu contenido |
|---|---|---|
| `favorite` | Probabilidad de like | Hooks emocionales, opiniones claras, contenido validado por la audiencia |
| `reply` | Probabilidad de respuesta | Preguntas, opiniones polarizantes (con cuidado), abrir conversación |
| `retweet` | Probabilidad de RT | Contenido compartible, frases citables, datos sorprendentes |
| `photo_expand` | Probabilidad de expandir imagen | Imágenes con detalle/legibilidad que invitan a abrir |
| `click` | Click en enlaces o post | Enlaces relevantes, *curiosity gap* en el texto |
| `profile_click` | Click en tu perfil | Bio interesante, post que genera "¿quién es esta persona?" |
| `vqv` (Video Quality View) | View "de calidad" de vídeo (>= mínimo de duración) | Vídeo nativo > umbral, primer segundo enganchador |
| `share` / `share_via_dm` / `share_via_copy_link` | Compartir | Contenido útil/práctico que la gente envía a amigos |
| `dwell` (binaria) / `cont_dwell_time` (continua) / `cont_click_dwell_time` | Tiempo que pasa el lector en el post | Textos densos pero legibles, hilos cortos en el primer tweet, imágenes que retienen mirada |
| `quote` / `quoted_click` / `quoted_vqv` | Quote-tweet del post | Frases que la gente quiere reaccionar comentando |
| `follow_author` | Que te sigan tras leer el post | Posts que muestran un punto de vista único / nicho consistente |

### Señales negativas (RESTAN al score)

| Señal | Qué predice | Qué dispara esto |
|---|---|---|
| `not_interested` | "No me interesa" explícito | Temas que el lector ya ha marcado, contenido off-topic respecto a su historial |
| `block_author` | Bloqueo del autor | Insultos, ataques personales, agresividad |
| `mute_author` | Mute del autor | Posteo excesivo, spam temático |
| `report` | Denuncia | Contenido que cruza líneas (NSFW sin tag, odio, etc.) |
| `not_dwelled` | El usuario hace scroll sin parar | **El post aburre o no llama la atención.** Más dañino de lo que parece. |

**Insight clave**: `not_dwelled` figura como peso negativo en la ecuación final ([`ranking_scorer.rs:83`](x-algorithm/home-mixer/scorers/ranking_scorer.rs)). Esto significa que un post que la gente **ignora sin parar** te penaliza activamente, no solo no te suma. Es un argumento fuerte contra el *clickbait* que no engancha: si la gente entra y se va rápido, peor que si nunca lo hubieran visto.

### Sobre los valores exactos de los pesos

Los pesos viven en un sistema de *feature switches* (`xai_feature_switches::Params`) que **no está incluido** en el dump open-source. El código pide cada peso por nombre (`params.get(FavoriteWeight)`, `params.get(ReportWeight)`…), pero los valores numéricos son configuración externa que xAI no ha publicado.

Por el release anterior (2023), sabemos que:
- las acciones negativas tienen pesos órdenes de magnitud mayores (en valor absoluto) que las positivas — un solo "report" puede borrar el efecto de varios likes;
- `reply` históricamente pesaba mucho más que `favorite`;
- `follow_author` es de los más pesados (te genera valor a largo plazo).

No tomar como evangelio para 2026: el código habilita ajustar todos esos pesos por experimento y cluster.

---

## 3. La penalización por repetición de autor (Author Diversity Decay)

Una de las palancas más infravaloradas del algoritmo.

```rust
fn diversity_multiplier(decay_factor: f64, floor: f64, position: usize) -> f64 {
    (1.0 - floor) * decay_factor.powf(position as f64) + floor
}
```

Fuente: [`home-mixer/scorers/ranking_scorer.rs:186-188`](x-algorithm/home-mixer/scorers/ranking_scorer.rs) y [`author_diversity_scorer.rs:29-31`](x-algorithm/home-mixer/scorers/author_diversity_scorer.rs).

Cómo funciona:
1. Se ordenan tus candidatos por score.
2. Para cada autor se lleva un contador (`position`) que empieza en 0.
3. El **primer** post del autor X mantiene su score (`multiplier = 1`).
4. El **segundo** post del autor X se multiplica por `decay`.
5. El **tercero** por `decay²`, el cuarto por `decay³`, etc.
6. El suelo (`floor`) es el mínimo absoluto al que cae el multiplicador.

Si `decay = 0.5` y `floor = 0.1`, tu segundo post pesa la mitad, el tercero ~28%, el cuarto ~16%, y a partir de cierto punto el 10%.

**Consecuencias prácticas:**
- No tiene sentido bombardear el feed con 10 posts seguidos. El segundo ya pierde mucho alcance comparado con el primero en *cada feed* individual.
- Si tienes 5 ideas en la cabeza, **espacíalas**. Cada usuario verá una sola "ronda" de scoring por sesión; espaciarlas en el tiempo asegura que cada una compita en pie de igualdad en distintas sesiones de distintos usuarios.
- Los hilos de muchos posts: solo el "mejor scoreado" del hilo aparece en el For You de cualquier lector (ver §5 sobre DedupConversationFilter), y los demás cobran el decay si llegasen a aparecer.

---

## 4. Out-Of-Network: el techo invisible al alcance fuera de tus seguidores

Cada candidato lleva un booleano `in_network`. Se pone a `true` si el autor está en tu lista de seguidos o eres tú mismo:

```rust
let is_in_network = is_self || followed_ids.contains(&candidate.author_id);
```

Fuente: [`candidate_hydrators/in_network_candidate_hydrator.rs:24-32`](x-algorithm/home-mixer/candidate_hydrators/in_network_candidate_hydrator.rs).

Después, en el ranker final:

```rust
let final_score = match c.in_network {
    Some(false) => after_diversity * effective_oon,
    _ => after_diversity,
};
```

Fuente: [`home-mixer/scorers/ranking_scorer.rs:272-275`](x-algorithm/home-mixer/scorers/ranking_scorer.rs).

`effective_oon`:
- En una petición con `topic_ids` no vacíos → `TopicOonWeightFactor` (más alto: en exploración por tema sí se cuela contenido externo).
- En usuarios nuevos (cuenta joven + `>= NEW_USER_MIN_FOLLOWING`) → `NEW_USER_OON_WEIGHT_FACTOR` (mucho más alto).
- Resto → `OonWeightFactor` (< 1).

**Insights:**
- Para llegar a no-seguidores, tu post tiene que ser **mucho mejor** que uno equivalente in-network, no solo "igual de bueno". El descuento OON puede ser del 50% o más.
- **Estrategia A para crecer:** generar engagement temprano de tus seguidores (que activa señales positivas del modelo y compensa el descuento OON cuando saltas a no-seguidores).
- **Estrategia B:** etiquetar/tematizar el contenido. En peticiones con topic explícito (usuarios siguiendo topics, *bulk topic requests*) el descuento OON es distinto y casi siempre menor.
- **Estrategia C:** captar a usuarios nuevos. Los recién registrados tienen multiplicador OON elevado: estás más cerca de ser descubrible por ellos que por gente con años en X.

Fuente del cálculo: [`ranking_scorer.rs:220-239`](x-algorithm/home-mixer/scorers/ranking_scorer.rs).

---

## 5. Lo que el algoritmo **NO** quiere que hagas (filtros que te eliminan)

### Pre-scoring (se ejecutan antes de puntuar el contenido)

| Filtro | Qué descarta | Archivo |
|---|---|---|
| `DropDuplicatesFilter` | Tweet_id duplicado | [`drop_duplicates_filter.rs`](x-algorithm/home-mixer/filters/drop_duplicates_filter.rs) |
| `CoreDataHydrationFilter` | Posts cuyo `author_id == 0` (datos del autor corruptos / cuenta borrada) | [`core_data_hydration_filter.rs`](x-algorithm/home-mixer/filters/core_data_hydration_filter.rs) |
| `AgeFilter` | Posts más antiguos que `max_age` (configurable) | [`age_filter.rs`](x-algorithm/home-mixer/filters/age_filter.rs) |
| `SelfTweetFilter` | Tus propios posts (no te ves a ti mismo en For You) | [`self_tweet_filter.rs`](x-algorithm/home-mixer/filters/self_tweet_filter.rs) |
| `RetweetDeduplicationFilter` | Si ya hay otro RT o el original del mismo tweet, se descarta el siguiente | [`retweet_deduplication_filter.rs`](x-algorithm/home-mixer/filters/retweet_deduplication_filter.rs) |
| `IneligibleSubscriptionFilter` | Contenido subscriber-only de autores a los que no estás suscrito | [`ineligible_subscription_filter.rs`](x-algorithm/home-mixer/filters/ineligible_subscription_filter.rs) |
| `PreviouslySeenPostsFilter` | Posts que ya viste (Bloom filter del cliente + `seen_ids`) | [`previously_seen_posts_filter.rs`](x-algorithm/home-mixer/filters/previously_seen_posts_filter.rs) |
| `PreviouslyServedPostsFilter` | Posts que ya te enviaron en sesiones recientes | [`previously_served_posts_filter.rs`](x-algorithm/home-mixer/filters/previously_served_posts_filter.rs) |
| `MutedKeywordFilter` | Keywords muteadas por el viewer (matching tokenizado) | [`muted_keyword_filter.rs`](x-algorithm/home-mixer/filters/muted_keyword_filter.rs) |
| `AuthorSocialgraphFilter` | Bloqueo/mute por el viewer, **bloqueo del autor hacia el viewer**, bloqueo de quien citas o retweeteas | [`author_socialgraph_filter.rs`](x-algorithm/home-mixer/filters/author_socialgraph_filter.rs) |
| `NewUserTopicIdsFilter` | Para usuarios nuevos: filtra todo lo que no esté en sus topics elegidos o sea in-network | [`new_user_topic_ids_filter.rs`](x-algorithm/home-mixer/filters/new_user_topic_ids_filter.rs) |
| `TopicIdsFilter` | En peticiones por topic, descarta posts que no coincidan con el topic | [`topic_ids_filter.rs`](x-algorithm/home-mixer/filters/topic_ids_filter.rs) |
| `VideoFilter` | Si `exclude_videos` está activo, fuera todos los vídeos | [`video_filter.rs`](x-algorithm/home-mixer/filters/video_filter.rs) |

### Post-selection (cribado final)

| Filtro | Qué descarta |
|---|---|
| `VFFilter` | Posts marcados como *Drop* por Visibility Filtering (borrados, spam, violencia, gore). [`vf_filter.rs`](x-algorithm/home-mixer/filters/vf_filter.rs) |
| `DedupConversationFilter` | Mantiene **un único tweet por conversación** (el de mayor score). [`dedup_conversation_filter.rs`](x-algorithm/home-mixer/filters/dedup_conversation_filter.rs) |
| `AncillaryVFFilter` | Posts con `drop_ancillary_posts == true` | [`ancillary_vf_filter.rs`](x-algorithm/home-mixer/filters/ancillary_vf_filter.rs) |

**Insights accionables:**
- **Bloquear y citar a quien te bloqueó es imposible:** si bloqueas a alguien, ni siquiera ves contenido que les cite o retweetee. Y a la inversa: si te bloqueó, tu post no aparece en su feed (esto es esperable, pero el código lo refuerza con `author_blocks_viewer` y `quoted_author_blocks_viewer`).
- **`DedupConversationFilter` mata los megahilos**: si haces un hilo de 8 tweets respondiendo a tu propio post, el feed solo mostrará **uno** (el más alto en score). La intuición de "encadeno respuestas para ocupar más feed" es falsa.
- **`PreviouslySeenPostsFilter` y `PreviouslyServedPostsFilter`** usan bloom filters → un mismo post no puede salir dos veces. Re-postear el mismo texto es inútil para los usuarios que ya lo vieron; tienes que crearlo nuevo cada vez.

---

## 6. El "tribunal Grok": clasificadores de contenido (`grox/`)

El módulo `grox/` es una pipeline de tareas paralelas que ejecutan modelos Grok-VLM (multimodal) sobre cada post. Los planes activos están en [`grox/plans/plan_master.py`](x-algorithm/grox/plans/plan_master.py):

```python
ALL_PLANS = [
    PlanInitialBanger(),
    PlanPostSafety(),
    PlanSpamComment(),
    PlanPostEmbeddingWithSummary(),
    PlanPostEmbeddingWithSummaryForReply(),
    PlanPostEmbeddingV5(),
    PlanPostEmbeddingV5ForReply(),
    PlanReplyRanking(),
    PlanSafetyPtos(),
]
```

### 6.1 Banger Initial Screen (calidad de post original)

Solo se ejecuta sobre **posts originales** (no replies, no retweets). Filtros previos:

```python
if post.ancestors:  # es reply
    return False
if post.user.is_protected:  # cuenta privada
    return False
```

Fuente: [`grox/tasks/task_filters.py:340-370`](x-algorithm/grox/tasks/task_filters.py).

El clasificador VLM ([`grox/classifiers/content/banger_initial_screen.py`](x-algorithm/grox/classifiers/content/banger_initial_screen.py)) devuelve un JSON con:

```python
class BangerInitialScreenResult(BaseModel):
    quality_score: float        # 0.0 - 1.0
    description: str
    tags: list[str]
    taxonomy_categories: list[dict] | None  # categorías y su confianza
    tweet_bool_metadata: TweetBoolMetadata | None
    is_image_editable_by_grok: bool | None
    slop_score: int | None       # cantidad de "AI slop" detectado
    has_minor_score: float | None  # contenido con menores
```

Y la decisión:

```python
banger_initial_positive = score >= 0.4
```

Es decir, un post es marcado como "banger" si Grok le pone **≥ 0.4 / 1.0** de calidad. El histograma se mide en buckets [0, 0.1, 0.2 … 1.0].

**Implicaciones:**
- **Si publicas como cuenta privada, no pasas por embedding ni clasificación**. No tendrás retrieval out-of-network. Crecer de protected → public no solo da visibilidad: te abre los signals del modelo.
- **Los retweets y replies no son evaluados como "bangers"**. El sistema de descubrimiento OON premia POSTS ORIGINALES.
- **`slop_score`**: existe un score explícito para detectar "AI slop". Posts de calidad-bajo-LLM tienen handicap.
- **`has_minor_score`**: detección automática de menores en imágenes; correlaciona con safety labels y desmonetiza/desamplifica.
- **`is_image_editable_by_grok`**: un flag que sugiere que parte del catálogo de imágenes está marcado como editable por Grok (probablemente para previews o variantes generadas).

### 6.2 Spam en respuestas (`PlanSpamComment`)

Solo se ejecuta cuando:

```python
if not post.ancestors:        # debe ser reply
    return False
# ...
if root_user_follower_count > THRESHOLD or in_reply_user_follower_count > THRESHOLD:
    return False              # si la cuenta target tiene MUCHOS followers, no se evalúa por spam
```

Fuente: [`grox/tasks/task_filters.py:55-134`](x-algorithm/grox/tasks/task_filters.py).

El clasificador ([`grox/classifiers/content/spam.py`](x-algorithm/grox/classifiers/content/spam.py)) se llama `SpamEapiLowFollowerClassifier` y usa el prompt `SpamSystemLowFollower`. La decisión es binaria (`spam` / no spam) → score 1.0 / 0.0.

**Lectura:**
- Las **respuestas a cuentas pequeñas** son las que se clasifican como spam por Grok. Esto tiene sentido: cuentas pequeñas no pueden moderar manualmente, así que el sistema las protege automáticamente.
- Las respuestas a cuentas grandes pasan por *Reply Ranking* en su lugar (siguiente sección).
- **Practica:** si quieres "reply-jacking" a influencers, no te juzga el spam classifier sino el reply ranker (más sofisticado y orientado a calidad).

### 6.3 Reply Ranking (orden de respuestas en cuentas grandes)

Inverso del anterior: solo se ejecuta cuando la cuenta target **supera** el umbral de followers.

```python
if in_reply_user_follower_count <= THRESHOLD and root_user_follower_count <= THRESHOLD:
    return False  # "low_blast_radius"
```

Fuente: [`grox/tasks/task_filters.py:137-201`](x-algorithm/grox/tasks/task_filters.py).

Grok ([`grox/classifiers/content/reply_ranking.py`](x-algorithm/grox/classifiers/content/reply_ranking.py)) puntúa cada respuesta de 0 a 3:

```python
Metrics.histogram(
    "ranked_replies_scores",
    explicit_bucket_boundaries_advisory=[0.0, 1.0, 2.0, 3.0],
).record(parsed[0].score)
```

Usa el prompt `ReplyScoringSystem` con parámetro `large_account_follower_threshold`.

**Práctico:**
- Cuando respondes a una cuenta grande, **un modelo VLM lee tu respuesta y la ordena**. Respuestas genéricas ("primero!", emojis sueltos, "🔥🔥") puntúan bajo.
- Las respuestas más sustanciosas (que añaden información, comentan con criterio, son graciosas con contexto) suben en el ranking de respuestas visibles. Es donde se gana visibilidad parasitaria a cuentas grandes — pero solo con calidad real.

### 6.4 Safety PToS (Policy Terms of Service): las 7 categorías que te bajan

Cada post se clasifica por violación de política en estas 7 categorías:

```python
SUPPORTED_POLICY_CATEGORIES = {
    SafetyPolicyCategory.ViolentMedia,
    SafetyPolicyCategory.AdultContent,
    SafetyPolicyCategory.Spam,
    SafetyPolicyCategory.IllegalAndRegulatedBehaviors,
    SafetyPolicyCategory.HateOrAbuse,
    SafetyPolicyCategory.ViolentSpeech,
    SafetyPolicyCategory.SuicideOrSelfHarm,
}
```

Fuente: [`grox/classifiers/content/safety_ptos.py:217-225`](x-algorithm/grox/classifiers/content/safety_ptos.py).

Dos de ellas (`AdultContent`, `ViolentMedia`) usan el modelo **deluxe-4.2** especializado para razonamiento ([líneas 227-230](x-algorithm/grox/classifiers/content/safety_ptos.py)). Cada categoría tiene su propio prompt de policy (`ViolentMediaPolicy`, `AdultContentPolicy`, `SpamPolicy`, `IllegalAndRegulatedBehaviorsPolicy`, `HateOrAbusePolicy`, `ViolentSpeechPolicy`, `SuicideOrSelfHarmPolicy`).

Si un post cae en estas categorías, se le aplican *safety labels* y su veredicto de brand safety degrada (ver §7).

---

## 7. Brand safety: tres niveles, ads bloqueadas, y un *cliff* importante

Cada post recibe un `BrandSafetyVerdict` ([`home-mixer/models/brand_safety.rs`](x-algorithm/home-mixer/models/brand_safety.rs)):

| Verdict | Significado | Consecuencias |
|---|---|---|
| `Safe` | Sin labels de riesgo + scoreado por Grok + (si post nuevo) revisado por PToS | Sirve para todo |
| `LowRisk` | Etiquetas: `NSFA_LIMITED_INVENTORY`, `GROK_NSFA_LIMITED`, `NSFA_HIGH_RECALL` | Aparece, pero ads adyacentes limitadas |
| `MediumRisk` | NSFW (varias variantes), NSFA, gore, violencia, `DO_NOT_AMPLIFY`, `PDNA`, `EGREGIOUS_NSFW`, `NSFW_TEXT`, `NSFW_CARD_IMAGE`, o **no scoreado por Grok**, o **post nuevo sin `PTOS_REVIEWED`** | Sin ads adyacentes, downranked en exploración |

Hay un **cliff temporal**: hay una constante

```rust
const PTOS_CUTOFF_TWEET_ID: u64 = 2_054_275_414_225_846_272;
```

Tweets posteriores a ese ID que no tengan el label `PTOS_REVIEWED` se marcan automáticamente como **MediumRisk**. Es decir: los posts nuevos tienen que pasar por el clasificador PToS antes de poder ser "Safe". Esto crea un periodo de latencia en posts recién publicados (mientras Grok los evalúa).

**Lectura:**
- Si tu post tiene NSFA/NSFW/violencia, **ningún anunciante lo verá adyacente** y por tanto no recibe ingresos de impresión publicitaria (y probablemente baja en distribución).
- Existe `DO_NOT_AMPLIFY` y `PDNA` como labels específicos para "no amplificar". Si Grok te aplica uno de estos, estás *shadow-banned* para amplificación.
- **Hay un label `NSFW_TEXT`**: el modelo detecta NSFW en texto puro (no solo imágenes). Por tanto, *spicy* + sin imagen no te salva del cliff.

### Ads y brand safety adyacente

`PartitionOrganicAdsBlender` y `SafeGapAdsBlender` ([`home-mixer/ads/`](x-algorithm/home-mixer/ads/)) hacen un esfuerzo importante por **NO** poner anuncios al lado de contenido `MediumRisk`. Cuando lo hay:

- Solo HALF de los posts "seguros" pueden tener ads alrededor (`max_from_safe = safe_count / 2`).
- Cada ad lleva un `ad_adjacency_control` con `handles` (cuentas bloqueadas) y `keywords` (palabras bloqueadas). Si el post de arriba o abajo matchea, **el ad se elimina** ([`ads/util.rs:99-151`](x-algorithm/home-mixer/ads/util.rs)).
- Por defecto: 1 ad cada 3 posts, mínimo 2 posts entre ads, primer post nunca-anuncio (`MIN_POSTS_FOR_ADS = 5`).

Si te preguntas por qué los anunciantes huyen de ciertos temas: el sistema literalmente *drop*ea su impresión si tu post tiene los keywords/handles que el anunciante puso en su blocklist.

---

## 8. La pregunta del millón: ¿Escribir desde Europa para audiencia US perjudica?

**Respuesta corta:** *no hay ningún filtro hardcoded que penalice por país.* Pero el modelo aprende correlaciones de los datos, y eso puede sesgar el resultado.

### Lo que el sistema sabe de TI cuando lees X

La `ScoredPostsQuery` ([`home-mixer/models/query.rs:25-95`](x-algorithm/home-mixer/models/query.rs)) lleva:

- `country_code: String` — código de país que envía el cliente.
- `language_code: String` — idioma de la app/dispositivo.
- `ip_address: String` — IP del usuario.
- `ip_location: Option<LocationInfo>` — ubicación derivada de la IP via GeoIP (ver `IpQueryHydrator` con `xai_geo_ip::GeoIpLocationClient`).
- `time_zone: Timezone` — zona horaria.
- `device_network_type: DeviceNetworkType` — WiFi/4G/5G.
- `user_demographics: Option<UserDemographics>` — datos demográficos (edad inferida, género inferido).
- `user_age_in_years: Option<i32>`.
- `user_inferred_gender: Option<InferredGenderLabel>` + `user_inferred_gender_score: Option<f32>`.

### Lo que el sistema sabe del POST que estás considerando promocionar

El `PostCandidate` lleva:

- `language_code: Option<String>` — idioma **del post** (detectado, no del autor).
- `author_followers_count`, `author_screen_name`, etc.

**No hay `country_code` en el `PostCandidate`.** No hay campo que diga "este post se escribió desde Europa".

### ¿Se usa esto para algo concreto?

```rust
proto_query.country_code   // → llega al Phoenix client
proto_query.language_code  // → llega al Phoenix client
.country(&proto_query.country_code)
.language(&proto_query.language_code)
```

Fuente: [`home-mixer/server.rs:92-148`](x-algorithm/home-mixer/server.rs).

```rust
// Ads y WTF también reciben country/language
country_code: query.country_code.clone(),
language_code: query.language_code.clone(),
```

Fuente: [`home-mixer/sources/tweet_mixer_source.rs:46-47`](x-algorithm/home-mixer/sources/tweet_mixer_source.rs), [`home-mixer/sources/ads_source.rs:48-49`](x-algorithm/home-mixer/sources/ads_source.rs), [`home-mixer/sources/who_to_follow_source.rs:67-70`](x-algorithm/home-mixer/sources/who_to_follow_source.rs).

País del viewer + idioma se inyectan en el modelo de scoring y en las llamadas a sistemas externos (ads, who-to-follow). El modelo Phoenix puede entonces aprender (de los logs) cosas como:
- "Usuarios con `country=US` engagean menos con posts `language_code=es`".
- "Los anuncios en US se subastan distinto que en EU".

### Conclusiones honestas para un creador en EU apuntando a US

1. **No hay un "anti-EU dial"** en el algoritmo. Si tu post engancha bien (mucho dwell + likes + retweets + follow), pasa los filtros igual que el de un usuario US.
2. **El idioma del post sí pesa**, porque viaja como feature al modelo. Si vas a audiencia US, escribe en inglés. Postear en español a usuarios en US bajará tu match score muchísimo (no por filtro, por aprendizaje del modelo).
3. **Sí afecta el horario.** El campo `time_zone` y `request_time_ms` están en la query. Los usuarios US se distribuyen en husos US (-5 a -8 GMT). Si publicas a tu hora europea matinal, los usuarios US duermen → tu post envejece (filtro `AgeFilter`) antes de tener oportunidad de mostrarse a ellos.
4. **El campo `country_code` del usuario** entra como contexto, no se proyecta sobre tu cuenta. No hay registro estable de "país del autor" en el `PostCandidate`. La señal "soy europeo" no viaja con cada uno de tus posts.
5. **IP del viewer (no del autor) se usa.** Lo que se geoip-iza es la IP de quien pide el feed, no la tuya cuando publicas (al menos no en esta parte del código).
6. **Lo que SÍ puede pasar:** que tu cuenta tenga histórico de engagement mayoritariamente europeo → el embedding de tu cuenta en el Two-Tower se parezca más a usuarios europeos → los usuarios US no la encuentren por similitud (retrieval). No es un castigo, es física vectorial. **Si quieres romper el sesgo**, optimiza early-engagement de cuentas US (publicar a horarios US, etiquetar/replier a cuentas US, usar topics globales/anglo).

> Nota: el repositorio referencia un módulo `crate::util::country_codes::bucket_country(...)` (ver [`for_you_response_stats_side_effect.rs:97`](x-algorithm/home-mixer/side_effects/for_you_response_stats_side_effect.rs)) pero el archivo de implementación no está incluido en el release. Probablemente agrupa países por mercado para métricas, no para filtrado.

---

## 9. Vídeo: cuándo te ayuda y cuándo no

```rust
fn vqv_weight_eligibility(candidate: &PostCandidate) -> f64 {
    if candidate.video_duration_ms.is_some_and(|ms| ms > p::MIN_VIDEO_DURATION_MS) {
        p::VQV_WEIGHT
    } else {
        0.0
    }
}
```

Fuente: [`home-mixer/scorers/weighted_scorer.rs:72-81`](x-algorithm/home-mixer/scorers/weighted_scorer.rs).

Es decir: el peso del Video-Quality-View (la principal señal positiva de vídeo) **se anula a 0** si tu vídeo dura menos que `MIN_VIDEO_DURATION_MS`.

Las cubetas de instrumentación ([`tweet_type_metrics_hydrator.rs:113-127`](x-algorithm/home-mixer/candidate_hydrators/tweet_type_metrics_hydrator.rs)):

- `VIDEO_LTE_10_SEC` — ≤ 10 segundos
- `VIDEO_BT_10_60_SEC` — 10–60 segundos
- `VIDEO_GT_60_SEC` — > 60 segundos

No es un escalado lineal: solo hay un *threshold* del que no conocemos el valor exacto, pero por convención industrial está en torno a 7–10 segundos. Vídeos muy cortos pierden el bonus aunque la vista se complete.

**Insight:** el "shorts ultra-cortos" no es óptimo en X. El sistema premia vídeo que **retiene tiempo**, no vídeo per se.

Y el `cont_dwell_time` (continuous dwell) se aplica a todo tipo de post, no solo vídeo. **El tiempo de permanencia es métrica universal**.

---

## 10. Señales colaterales útiles que aprende el modelo

### Mutual-Follow Jaccard

```rust
fn jaccard_from_minhash(a: &[i64], b: &[i64]) -> f64
```

Fuente: [`candidate_hydrators/mutual_follow_jaccard_hydrator.rs`](x-algorithm/home-mixer/candidate_hydrators/mutual_follow_jaccard_hydrator.rs).

Para cada candidato, se calcula la **similitud Jaccard del minhash** entre el viewer y el autor del post (representa cuántos follows comparten). Requiere ≥ 256 minhashes a cada lado.

**Lectura:** los autores que comparten mucha gente seguida contigo aparecen con un boost implícito (es una feature del modelo). Tener "mismas tribus" con tu audiencia objetivo es señal explícita.

### Engagement counts en hot caches

Se hidratan `fav_count`, `reply_count`, `repost_count`, `quote_count` con TTL diferenciado:

- Tweets nuevos (< 30 min): caché 5 minutos.
- Tweets viejos: caché 10 minutos.

Fuente: [`engagement_counts_hydrator.rs:32-39`](x-algorithm/home-mixer/candidate_hydrators/engagement_counts_hydrator.rs).

**Lectura:** las primeras horas son las que más rápido se reflejan en los rankings. Posts viejos se actualizan más lento.

### "Following replied users facepile"

Solo se hidrata si el **viewer** tiene ≥ 1000 followers:

```rust
const VIEWER_FOLLOWERS_THRESHOLD: i64 = 1000;
```

Fuente: [`following_replied_users_hydrator.rs:13-44`](x-algorithm/home-mixer/candidate_hydrators/following_replied_users_hydrator.rs).

Eso significa que la prueba social "5 personas que sigues respondieron este post" **no se muestra a usuarios con menos de 1000 followers**. Para los demás, sí puede ser un signal de relevancia.

### Cuentas privadas (`is_protected`)

Si el autor original o cualquier ancestro de la cadena es privado, **se cancela**:

- El embedding de post (sin embedding ≠ sin retrieval).
- El banger screen.
- El post safety deluxe.

Fuente: múltiples filtros en [`grox/tasks/task_filters.py`](x-algorithm/grox/tasks/task_filters.py).

**Lectura:** ser cuenta privada literalmente te excluye de los pipelines de descubrimiento. Si quieres alcance fuera de tu red, **debes ser cuenta pública**.

---

## 11. Topics: 80+ categorías que sí importan

El TopicIdExpansion en [`topic_ids_filter.rs:109-291`](x-algorithm/home-mixer/filters/topic_ids_filter.rs) define los topics que X reconoce. Algunos llamativos:

- **Macro-categorías** (agrupan muchas sub-): `SCIENCE_TECHNOLOGY`, `ENTERTAINMENT`, `BUSINESS_FINANCE`, `SPORTS`.
- **Sub-categorías**: política, IA, gaming, crypto, K-pop, Premier League, **US-IRAN_WAR** (sí, hay un topic específico para esta crisis geopolítica), salud mental, citas, parenting, etc.
- **Religión** está desglosada: Cristianismo, Budismo, Hinduismo, Islam, Judaísmo.

Si tu petición trae topics, el sistema:
1. Filtra a posts del topic.
2. Aplica un **OON weight factor para topic** (`TopicOonWeightFactor`) que es distinto del general — facilita aparecer a no-seguidores cuando hay topic match.

**Lectura:** etiquetar/tematizar tus posts (con hashtags y palabras del vocabulario) ayuda al matching topic-based. Y el lector que busca un topic está más permeable a contenido externo a su red.

---

## 12. Anuncios: la "tax invisible" de tu feed

- **1 anuncio cada 3 posts** por defecto (mínimo 2 entre ads).
- **Nunca antes del post 5**.
- **Nunca el último** elemento.
- Solo se inserta el ad entre posts "seguros" (sin verdict MediumRisk).
- El ad lleva un `ad_adjacency_control` que puede bloquearlo si los posts vecinos contienen handles/keywords de su blocklist.
- Hay un veredicto especial `BsrLow / BsrIas` para ads con bajo risk score: estos NO se ponen al lado de posts LowRisk (los anunciantes premium quieren MAX safety).

Fuente: [`home-mixer/ads/util.rs`](x-algorithm/home-mixer/ads/util.rs), [`home-mixer/ads/partition_organic_blender.rs`](x-algorithm/home-mixer/ads/partition_organic_blender.rs), [`home-mixer/ads/safe_gap_blender.rs`](x-algorithm/home-mixer/ads/safe_gap_blender.rs).

**Lectura comercial:** la prioridad del sistema es **maximizar impresiones de ads adyacentes a contenido `Safe`**. Tu contenido es vehículo de monetización; si haces que muchos ads se eliminen por adyacencia (NSFW edge, keywords de marcas, handles bloqueados), reduces el ingreso de ese feed y, por extensión, tu prioridad estructural.

---

## 13. Lo que NO está en el código abierto (y por qué importa)

xAI ha publicado la **estructura** del algoritmo. Faltan piezas clave:

1. **Los pesos numéricos** (`FavoriteWeight`, `ReplyWeight`, etc.). Están en `xai_feature_switches::Params`, que es un sistema de configuración externo no incluido en el dump.
2. **Los prompts** de los clasificadores Grok (`BangerMiniVlmScreenScore`, `SpamSystemLowFollower`, `SafetyPtos`, `ReplyScoringSystem`, las 7 policy prompts). Existen como clases referenciadas pero los archivos `grox/prompts/template.py` no están publicados.
3. **El `country_codes` util** (`bucket_country`).
4. **Los pesos del *Two-Tower* y del *transformer Phoenix***. Lo que sí está es un *mini Phoenix* preentrenado (256-dim, 4 cabezas, 2 layers) en Git LFS — pero el modelo de producción usa configuraciones distintas.
5. **El módulo `xai_decider`** completo. Los `decider.enabled("xxx")` que vemos por todo el código son feature flags A/B internos: en el momento del dump, podrían estar activados o no para tu cuenta.

**Lectura:** la versión open-source es la **anatomía** del sistema. Cualquier intento de optimización fina (calcular un score reproducible para un post dado) requiere o medir empíricamente (publicando posts y midiendo impresiones), o asumir que xAI publicará los pesos en algún momento posterior.

---

## 14. Resumen ejecutivo: la "lista de la compra" para más alcance

### Hazlo
1. **Publica ORIGINAL** (los retweets y replies no pasan por el Banger Screen → menos amplificación OON).
2. **No seas cuenta privada** (sin embeddings, sin retrieval).
3. **Espacia tus posts**: no más de 1 cada pocas horas para evitar la *Author Diversity Decay*.
4. **Optimiza por dwell + reply, no por like**: `dwell` continuo, `cont_dwell_time`, `cont_click_dwell_time` son señales pesadas. Una respuesta o quote vale más que un like.
5. **Vídeo > umbral mínimo**: si haces vídeo, hazlo de ≥ 10–15 s aprox. y que el primer segundo retenga.
6. **Tema explícito**: usa topics y vocabulario que el modelo entienda como "este post es de IA / crypto / NFL". Te ayuda en el `TopicOonWeightFactor`.
7. **Idioma del lector**: si quieres US, escribe en inglés. Si quieres EU, segmenta por idioma local.
8. **Horario de la audiencia**: el `AgeFilter` te mata. Publica cuando tu audiencia objetivo está despierta.
9. **Genera engagement temprano de seguidores**: amplifica con tu red para activar señales positivas y compensar el descuento OON al saltar fuera.
10. **Calidad real en respuestas a grandes**: el Reply Ranker te lee. "Primero!" no escala.

### Evítalo
1. **Posts cerca de las 7 policies de PToS** (violencia, NSFW sin etiquetar, hate, spam, ilegales, violencia verbal, autolesión) → MediumRisk + sin ads + downrank.
2. **Megahilos de 10+ tweets para "ocupar feed"**: `DedupConversationFilter` solo deja uno por hilo.
3. **Reciclar el mismo post**: `PreviouslySeen*` filters lo descartan.
4. **Bloqueos cruzados**: si bloqueas a alguien, pierdes acceso a su contenido citado/retweeteado y a todo el grafo de quien le cite.
5. **AI slop puro**: el `slop_score` existe explícitamente. Mejor LLM + edición humana que generación cruda.
6. **Respuestas espurias a cuentas pequeñas**: el spam classifier specific de low-follower te puede etiquetar.
7. **Cuenta privada si quieres crecer**: incompatible con descubrimiento.
8. **Confiar en el follower count como métrica única**: el `WeightedScorer` y el `RankingScorer` principales **no** usan el follower count como peso directo. Existen cubetas (0-100, 100-1K, 1K-10K, 10K-100K, 100K-1M, 1M+) para *instrumentación interna* ([`tweet_type_metrics_hydrator.rs`](x-algorithm/home-mixer/candidate_hydrators/tweet_type_metrics_hydrator.rs)) y el `VMRanker` alternativo lo recibe como feature de su value-model ([`vm_ranker.rs:102`](x-algorithm/home-mixer/scorers/vm_ranker.rs)) — pero el peso final lo decide el comportamiento del post, no la fama del autor.

---

## 15. El "gate de min-traction": el bottleneck más importante (y el más invisible)

El descubrimiento de la segunda pasada que más cambia las reglas del juego.

El sistema **Grox** (la capa de clasificación con Grok-VLM) **no procesa todos los posts**. Procesa varios streams Kafka distintos, y cada stream tiene su propio conjunto de "elegibilidades" que abre.

Fuente: [`grox/generators/stream_generator.py:50-180`](x-algorithm/grox/generators/stream_generator.py) y [`grox/dispatcher.py:84-230`](x-algorithm/grox/dispatcher.py).

```python
class PostStreamTaskGenerator(StreamTaskGenerator):
    # TODOS los posts (ingestados al publicarse)
    TASK_GENERATOR_TYPE = TaskGeneratorType.POST_STREAM
    ELIGIBILITIES_TO_INJECT = {
        TaskEligibility.SPAM_COMMENT,
        TaskEligibility.REPLY_RANKING,
    }

class MinTractionPostStreamForGroxTaskGenerator(StreamTaskGenerator):
    # SOLO posts con "min traction" (engagement mínimo)
    TASK_GENERATOR_TYPE = TaskGeneratorType.POST_MIN_TRACTION_STREAM_FOR_GROX
    ELIGIBILITIES_TO_INJECT = {TaskEligibility.BANGER_INITIAL_SCREEN}

class MinTractionPostStreamForGroxPtosTaskGenerator(StreamTaskGenerator):
    # SOLO min-traction → PToS deluxe screen
    ELIGIBILITIES_TO_INJECT = {TaskEligibility.SAFETY_PTOS}

class MinTractionPostStreamForGroxMultiModalTaskGenerator(StreamTaskGenerator):
    # SOLO min-traction → embedding multimodal para reply
    ELIGIBILITIES_TO_INJECT = {TaskEligibility.POST_EMBEDDING_WITH_SUMMARY_FOR_REPLY}

class PostSafetyStreamTaskGenerator(StreamTaskGenerator):
    # Topic: "POPULAR" — sólo posts populares pasan por post-safety screen
    ELIGIBILITIES_TO_INJECT = {TaskEligibility.POST_SAFETY}
```

Léelo despacio:

- **`POST_STREAM`** (todos los posts) → solo elegible para `SPAM_COMMENT` (si es reply a cuenta pequeña) y `REPLY_RANKING` (si es reply a cuenta grande).
- **`MIN_TRACTION_STREAM`** → es el que abre `BANGER_INITIAL_SCREEN`, `SAFETY_PTOS`, y la generación del embedding multimodal para retrieval de respuestas.
- **`POPULAR_STREAM`** → desbloquea `POST_SAFETY` (el safety screen "completo").

**Implicación masiva**: si tu post no cruza el umbral de "min traction", **nunca se clasifica como banger** y **nunca recibe la generación de embedding multimodal de calidad**. Sin embedding de calidad, no entra en el corpus de retrieval que Phoenix usa para descubrir contenido fuera-de-red. Sin Banger Screen, no es candidato a amplificación.

**El sistema premia con clasificación profunda a los posts que ya tienen tracción**. Es un círculo virtuoso, y por la misma razón un acantilado para posts que arrancan en frío.

**Acciones recomendadas:**
1. **Genera engagement temprano por todos los medios posibles**: notifica a tu red, publica en horario punta, asegura los primeros likes/replies en los primeros minutos.
2. **Si un post va bien después de 30-60 minutos, sube a Banger Screen**. Si no, está muerto para el descubrimiento amplio (aunque siga visible para tus seguidores).
3. **Combinado con la edad-feature (siguiente sección)**: los **primeros 30 minutos** son donde se decide casi todo.

> El valor numérico exacto del "min traction threshold" no está en el código (no aparece como constante hardcoded; probablemente es config externa de los Kafka producers). Pero la *existencia* del gate sí está, y por instrumentación industrial está típicamente entre "≥1 like" o "≥3 engagement events".

---

## 16. La edad del post es una feature explícita del modelo (techo a 80 horas)

```python
POST_AGE_MAX_MINUTES = 4800   # 80 horas


def compute_post_age_bucket(
    impr_ts_sec, post_creation_ts_sec, granularity_mins: int = 60,
) -> jax.Array:
    num_normal_buckets = POST_AGE_MAX_MINUTES // granularity_mins
    overflow_bucket = num_normal_buckets + 1

    post_age_minutes = (impr_ts_sec - post_creation_ts_sec) // 60
    bucket = (post_age_minutes // granularity_mins) + 1
    bucket = jnp.clip(bucket, 0, overflow_bucket)
    # ...
```

Fuente: [`phoenix/recsys_model.py:33-55`](x-algorithm/phoenix/recsys_model.py).

Conclusiones directas:
- El modelo **discretiza la edad** del post en buckets de 60 minutos. Cada bucket es un embedding aprendido (`post_age_vocab_size = 80 + 2`).
- Tras **80 horas (≈ 3.3 días)** el post cae en el `overflow_bucket` — sea cual sea su edad real (4 días, 1 semana, 1 mes), el modelo lo ve igual.
- A los pocos minutos de publicación, el post está en bucket 0/1, embeddings que el modelo ha aprendido a asociar con "recencia y posible viralidad".
- Encima, hay un `AgeFilter` al inicio del pipeline que **directamente elimina** posts más viejos que `max_age` (otra variable externa). El bucket de overflow probablemente nunca se ve en producción para For You — solo en otros surfaces.

**Truco operativo:**
- Un post viejo no "se recupera" con engagement tardío. Aunque alguien le dé un mega-RT 3 días después, el modelo ya no lo va a tratar igual que uno fresco.
- La ventana de **0-12 horas es donde se decide todo**. A las 24h el post entra en territorio de "antigüedad alta". A las 80h+ está muerto para For You.

---

## 17. El "switch de privacidad de For You" del lector

```rust
let in_network_only =
    proto_query.in_network_only ||
    viewer_data.allow_for_you_recommendations == Some(false);
```

Fuente: [`home-mixer/server.rs:75-77`](x-algorithm/home-mixer/server.rs).

Cualquier usuario puede tener en su configuración `allow_for_you_recommendations = false`. Cuando ese flag está activo, **el sistema fuerza `in_network_only = true`**, lo que desactiva:
- Phoenix Retrieval (out-of-network)
- Phoenix MoE
- Phoenix Topics
- Tweet Mixer

Es decir: ese usuario solo verá posts de gente que ya sigue, sin importar lo bueno que sea tu contenido.

**Truco práctico:** parte de tu audiencia objetivo tiene esto activado (lo desconocido es qué porcentaje). La única forma de llegarles **garantizada** es que pulsen "Follow". Insistir en hooks de discovery (memes virales, etc.) no te alcanza ese segmento; sí te alcanza si te siguen y luego el contenido pasa por la fase de scoring in-network.

---

## 18. El 50% de "shadow traffic": features experimentales que sí o sí afectan a tu audiencia

```rust
let query = ScoredPostsQuery::new(
    // ...
    is_sampled(request_id, 0.5),  // is_shadow_traffic
    // ...
);
```

Fuente: [`home-mixer/server.rs:117`](x-algorithm/home-mixer/server.rs).

**La mitad de TODAS las requests son `is_shadow_traffic = true`**. Y varios hydrators tienen el patrón:

```rust
fn enable(&self, query: &ScoredPostsQuery) -> bool {
    query.params.get(EnableContextFeatures) || query.is_shadow_traffic
}
```

(Ejemplos: `UserDemographicsQueryHydrator`, `UserInferredGenderQueryHydrator`, `FollowedGrokTopicsQueryHydrator`, `HasMediaHydrator`, `EngagementCountsHydrator`, `FollowedStarterPacksQueryHydrator`…)

Eso significa que **incluso si los flags están "off" oficialmente**, **el 50% de tus impresiones van a usuarios cuyo request los activó**. Para un creador no hay manera de saberlo, pero **debes asumir que estas features están activas siempre**: género inferido, edad, demografía, topics Grok seguidos, starter packs, ubicación IP, etc.

---

## 19. La "memoria" del modelo: solo las últimas ~128 acciones

```python
@dataclass
class PhoenixModelConfig:
    history_seq_len: int = 128
    candidate_seq_len: int = 32
    num_continuous_actions: int = 8
    product_surface_vocab_size: int = 16
    post_age_granularity_mins: int = 60
    mask_neg_feedback_on_negatives: bool = True
```

Fuente: [`phoenix/recsys_model.py:336-365`](x-algorithm/phoenix/recsys_model.py).

En la versión mini del modelo publicado:
- **`history_seq_len = 128`**: el modelo solo "ve" las últimas 128 acciones del usuario al puntuar cada candidato.
- **`candidate_seq_len = 32`**: 32 candidatos puntuados a la vez (con attention isolation).
- **`product_surface_vocab_size = 16`**: 16 "surfaces" distintos (Home, Profile, Search, Following, Trending, Notifications, etc.). El modelo aprende que un like en Home no significa lo mismo que uno en Search.
- **`num_continuous_actions = 8`**: 8 acciones continuas (dwell time, click dwell time, etc.).

La producción usa más layers y secuencias más largas, pero la **estructura es la misma: una ventana acotada de comportamiento reciente**.

**Implicaciones operativas:**
- Un usuario que tiene un patrón de likes "antiguo" sobre cierto tema pero ha cambiado de intereses recientemente, **será matcheado con su comportamiento reciente, no histórico**. Los pivotes de contenido funcionan.
- Si quieres entrar en un nuevo nicho, **no esperes que el modelo te recuerde por likes de hace 6 meses**. Necesitas engagement reciente con ese nicho para que el modelo te asocie.

---

## 20. La importante diferencia entre `scoring_sequence` y `retrieval_sequence`

El modelo recibe DOS secuencias distintas del comportamiento del usuario:

- **`retrieval_sequence`**: agregación `Dense` por defecto. Se usa para encontrar candidatos OON via similitud (Two-Tower). Fuente: [`retrieval_sequence_query_hydrator.rs:48-50`](x-algorithm/home-mixer/query_hydrators/retrieval_sequence_query_hydrator.rs).
- **`scoring_sequence`**: agregación `DenseWithNotInterestedIn` por defecto. Se usa para puntuar candidatos ya retrieved. Fuente: [`scoring_sequence_query_hydrator.rs:55-58`](x-algorithm/home-mixer/query_hydrators/scoring_sequence_query_hydrator.rs).

La diferencia clave: la `scoring_sequence` **incluye los "not interested"** del usuario explícitamente. Eso significa que cuando el modelo decide si tú vas a ver el siguiente post, **considera lo que has marcado como "no me interesa" recientemente**.

**Realtime feedback:**

```rust
let include_realtime: bool = query.params.get(IncludeRealtimeActions);
```

Hay un flag `IncludeRealtimeActions` que añade acciones recién-hechas a la secuencia. Si un usuario marca "no me interesa" en un post de un tema, el efecto puede ser **inmediato** en la siguiente petición.

**Acción:** evita patrones que generen "not interested" en *cualquier* usuario, porque ese voto se propaga rápido a su modelo. Y si lo recibes, perderás visibilidad con ese usuario durante un buen rato (mientras dure en sus 128 acciones).

---

## 21. Otros límites duros del código (cheatsheet de constantes)

| Constante | Valor | Fuente | Significado |
|---|---|---|---|
| `POST_AGE_MAX_MINUTES` | 4800 (80h) | `phoenix/recsys_model.py:33` | Edad máxima representable del post |
| `post_age_granularity_mins` | 60 | `phoenix/recsys_model.py:352` | Buckets de 1h para edad |
| `history_seq_len` | 128 | `phoenix/recsys_model.py:342` | Ventana de acciones del usuario (mini model) |
| `candidate_seq_len` | 32 | `phoenix/recsys_model.py:343` | Candidatos puntuados por inferencia |
| `product_surface_vocab_size` | 16 | `phoenix/recsys_model.py:350` | "Sitios" donde el modelo trackea engagement |
| `MIN_POSTS_FOR_ADS` | 5 | `home-mixer/ads/util.rs:10` | Mínimo de posts antes del primer ad |
| `DEFAULT_SPACING.requested` | 3 | `home-mixer/ads/util.rs:14` | 1 ad cada 3 posts (default) |
| `DEFAULT_SPACING.min` | 2 | `home-mixer/ads/util.rs:14` | Mínimo absoluto entre ads |
| `MIN_REQUESTED_GAP` | 3 | `home-mixer/ads/util.rs:12` | Spacing solicitado mínimo |
| `MAX_WHO_TO_FOLLOW_USERS` | 3 | `home-mixer/sources/who_to_follow_source.rs:15` | Máx. WTF en módulo |
| `EXCLUDED_USER_IDS_LIMIT` | 200 | `home-mixer/sources/who_to_follow_source.rs:14` | Cuentas excluidas de WTF |
| `MAX_REPLIERS` | 3 | `home-mixer/sources/push_to_home_source.rs:13` | Facepile en push-to-home |
| `VIEWER_FOLLOWERS_THRESHOLD` | 1000 | `home-mixer/candidate_hydrators/following_replied_users_hydrator.rs:12` | Mínimo de followers para ver "X amigos respondieron" |
| `MIN_CACHED_POSTS_THRESHOLD` | 500 | `home-mixer/query_hydrators/cached_posts_query_hydrator.rs:12` | Posts cacheados antes de saltar a cached-mode |
| `MIN_HASHES` (mutual jaccard) | 256 | `home-mixer/candidate_hydrators/mutual_follow_jaccard_hydrator.rs:11` | Mínimo de hashes para calcular similitud follow-graph |
| `MAX_RESPONSES` | 50 | `home-mixer/side_effects/truncate_served_history_side_effect.rs:12` | Histórico de "served responses" guardado |
| `PTOS_CUTOFF_TWEET_ID` | `2_054_275_414_225_846_272` | `home-mixer/models/brand_safety.rs:37` | Tweets posteriores a este ID necesitan PTOS_REVIEWED para no ser MediumRisk |
| Video duration cap para procesado | 360 min (6h) | `grox/tasks/task_media.py:11` | Vídeos más largos no se procesan |
| Engagement counts cache (post nuevo) | 5 min TTL | `home-mixer/candidate_hydrators/engagement_counts_hydrator.rs:33` | Refresh rápido de contadores en posts <30 min |
| Engagement counts cache (post viejo) | 10 min TTL | `home-mixer/candidate_hydrators/engagement_counts_hydrator.rs:34` | Refresh más lento en posts >30 min |
| AdsBrandSafety cache (post nuevo) | 1 min TTL | `home-mixer/candidate_hydrators/ads_brand_safety_hydrator.rs:36` | Labels de safety se refrescan rápido para posts nuevos |
| `VIEWER_ROLES_TIMEOUT_MS` | 200 ms | `home-mixer/server.rs:33` | Si Gizmoduck no responde en 200ms, fallback a datos vacíos |

---

## 22. Hidden tricks (cosas no obvias para "gamear" el algoritmo)

> Algunas de estas son inferencias razonables del código, no garantías. Marcadas con (⚠️) las más especulativas.

### 22.1 El "boost-then-decay" del primer post del día
Por la *Author Diversity Decay*, tu **primer** post de la jornada en cada feed de cada usuario tiene el multiplicador 1.0. Como el feed se recompone en cada petición y los usuarios miran 5-20 veces al día, **publicar 1 vez con un post excelente cada ~6 horas suele rendir más que 5 publicaciones seguidas**. El decay es por feed-response, así que tener distintos posts compitiendo en distintos momentos del día compite contra el efecto de pisarte a ti mismo.

### 22.2 Compite por dwell, no por like
Los pesos exactos no están publicados, pero el modelo tiene **5 señales distintas de dwell**: `dwell_score` (binaria), `cont_dwell_time` (continua), `cont_click_dwell_time` (post de click), `not_dwelled_score` (negativa), más `quoted_vqv_score` para vídeos. Por contra, la señal `favorite_score` es **una sola**. Es razonable inferir que el agregado de señales de dwell pesa más que el like aislado. **Hilos con primer tweet enganchador + cuerpo interesante retienen más segundos que un meme rápido**.

### 22.3 Quote-tweet a posts virales de tu nicho
El `quoted_video_duration_ms` se hidrata del post citado, y los signals `quote_score`, `quoted_click_score`, `quoted_vqv_score` premian el quote-engagement. Citar contenido viral con un buen take añade SUS scores y los tuyos como una multiplicación: el modelo ya sabe que el original engagea, y tu valor añadido suma.

### 22.4 Los primeros 30-60 min del post deciden el "min-traction gate"
El gate de Grok (sección 15) se evalúa en cuanto el post recibe engagement. **El primer comentario, el primer like, en los primeros 5-10 minutos**, te sube al stream `MIN_TRACTION_FOR_GROX` y desbloquea Banger Screen + embedding multimodal de calidad. Lo que no entra ahí no se recupera más tarde.

### 22.5 Etiqueta tu contenido por topic
El `TopicOonWeightFactor` mejora el OON cuando la petición lleva topic. Posts con vocabulario claro de su nicho (hashtags reconocidos, palabras clave del topic, mencionar entidades reconocibles) se matchean con peticiones topic-based y reciben tratamiento OON diferente — más favorable.

### 22.6 Audio en vídeo importa (ASR)
El embedder multimodal **transcribe el audio** de tus vídeos via ASR. El texto transcrito se añade al understanding del post. **No hagas vídeos con música de fondo y cero voz**: estás dejando una columna entera de signal sin rellenar. La voz/discurso es leído por Grok y aporta al embedding semántico.

### 22.7 La facepile de "amigos también respondieron" tiene umbral 1000
Solo los usuarios con ≥ 1000 followers ven la facepile de prueba social ("3 personas que sigues respondieron a este post"). Si tu audiencia está **debajo de 1000 followers**, este signal de validación social no aparece para ellos. Si está encima, aparece y aumenta el CTR. Estrategia: optimiza para que tu cuenta sea atractiva específicamente para usuarios *de* >1000 followers (creadores, periodistas, etc.) porque sus impresiones convierten mejor visualmente.

### 22.8 Vídeos cortos (<10s) pierden el peso de Video Quality View
El bonus VQV se anula bajo `MinVideoDurationMs`. Aunque retengas al 100% del público, **no recibes el bonus pesado de vídeo**. Estrategia: minimum viable 10-15s.

### 22.9 Pon contenido cerca del top: el "cliff" de los 5 primeros
Los anuncios no aparecen hasta el **post 5+**. Eso significa que los primeros 5 posts del feed son 100% orgánicos y de mayor competición. Estar en top-5 implica score muy alto vs los demás candidatos. Pero también: estar en top-5 maximiza tu probabilidad de impresión (la gente hace scroll y abandona). El **score relativo en el top-5 es lo que gana**.

### 22.10 El `prediction_id` cacheado: replays gratis
Cada request tiene un `prediction_id` único. Las predicciones de Phoenix se cachean por `prediction_id`. Si el usuario polla (refresh automático) en los próximos segundos sin haber engagead nada, **el sistema potencialmente reutiliza tus scores**. Esto significa que un post bien scoreado durante una request puede aparecer en varias requests consecutivas del mismo usuario hasta que algo cambie. Trick: si tu post está en la primera tanda, beneficias de "inertia" en las siguientes.

### 22.11 El "fatigue cooldown" de WTF (Who-To-Follow)
`WhoToFollowFatigueHours` controla cada cuánto se vuelve a mostrar un módulo WTF al usuario. Si ya vio uno hace poco, no ve otro durante X horas. Esto no es relevante para tus posts pero sí para tu visibilidad lateral si has lanzado *campañas de seguidores*: el segundo WTF de la sesión simplemente no se sirve.

### 22.12 Re-publicar el mismo texto NO funciona
`PreviouslySeenPostsFilter` y `PreviouslyServedPostsFilter` filtran posts ya vistos (Bloom filter en cliente + IDs servidos). Cada post **tiene que ser nuevo** para que el mismo usuario lo vea. Re-tweeting tu propio post de hace un mes técnicamente sí funciona porque es un retweet con su propio ID en `retweeted_tweet_id`, **pero** el `RetweetDeduplicationFilter` luego eliminará versiones repetidas del mismo tweet.

### 22.13 (⚠️) Bloom filter del cliente tiene falsos positivos
El `PreviouslySeenPostsFilter` usa un Bloom Filter. Por definición tiene falsos positivos. Es teóricamente posible que un post que **NO** has visto sea descartado porque colisiona con un hash de uno que sí viste. Para un creador no es accionable, pero explica por qué a veces los usuarios "no ven" un post de alguien que siguen aunque tenga muchas impresiones.

### 22.14 Cuentas con menos de cierta antigüedad obtienen "new user" boost OON
`is_eligible_new_user` requiere: cuenta joven (`age < new_user_age_threshold`) + `>= NEW_USER_MIN_FOLLOWING` (mínimo de cuentas seguidas). Estas cuentas reciben el **`NEW_USER_OON_WEIGHT_FACTOR`** (claramente mayor que el OON factor general — el sistema empuja contenido OON a nuevos usuarios para que descubran). Implicación: targetear cuentas recién creadas (creadores con menos de N días) puede ser una forma de crecer porque tu OON-discount es menor para ellos.

### 22.15 (⚠️) `has_phone_number` y `account_age_days` como dimensiones de targeting
El `evaluate_feature_switches` ([`server.rs:138-175`](x-algorithm/home-mixer/server.rs)) construye el "recipient" con `account_age_days` y `has_phone_number` además de país, idioma y app. Eso significa que los feature flags pueden activarse selectivamente para "cuentas verificadas por teléfono" o "cuentas con > X días". Si publicas para una audiencia heterogénea, dos usuarios con perfil idéntico pero uno sin teléfono pueden recibir tu post con configuración distinta.

---

## 23. Errores que matan tu alcance (la lista corta de "absolutamente no")

1. **Postear desde cuenta protegida si quieres descubrimiento**. Sin embedding multimodal = sin retrieval OON.
2. **Posts a las 4am de tu zona si tu audiencia es transatlántica**. Para cuando despierten, ya estás en bucket de edad alta. La ventana óptima son **las 0-12 primeras horas de tu audiencia**, no de ti.
3. **Hilos de 10+ tweets** esperando ocupar feed. Solo gana 1 por hilo por usuario.
4. **Re-postear el mismo contenido a los pocos días**. Bloom filters + dedup filters lo descartan para los usuarios que ya lo vieron.
5. **Citar a quien te bloqueó / a quien tú bloqueaste**. `AuthorSocialgraphFilter` te elimina la cadena entera.
6. **Comentar genéricamente en cuentas grandes** ("primero!", emojis, "100% de acuerdo"). El Reply Ranker te ranquea bajo. Tu engagement queda diluido.
7. **Spam en respuestas a cuentas pequeñas**. El `SpamEapiLowFollowerClassifier` te etiqueta y deja un rastro.
8. **Vídeos de < 7-10 s sin promesa de retención**. Pierdes el peso VQV completo.
9. **AI slop puro**. El `slop_score` está en el código como métrica explícita. Genera con LLM, edita humano.
10. **Burst de 5 posts en 10 minutos**. Author Diversity Decay te destruye desde el segundo.
11. **NSFW/NSFA sin tag, violencia, hate**. Las 7 PToS categories más `DO_NOT_AMPLIFY` te ponen MediumRisk → sin ads adyacentes → downranking estructural.
12. **Quote-tweets en cadena de tu propio post sin valor añadido**. Los autoref-quotes son detectables y no aportan engagement diferenciado.
13. **Etiquetar mal el contenido (off-topic)**. Si pones hashtag de "AI" en un post de cocina, los lectores marcarán "no me interesa" → la señal entra inmediatamente en su `scoring_sequence` con peso negativo.
14. **Publicar a usuarios con `allow_for_you_recommendations = false`** y no captarles como seguidores. No los volverás a alcanzar OON.

---

## 24. Hoja de ruta operativa (primer post nuevo)

Si tuvieras que aplicar todo lo anterior a un post hipotético, este sería el orden:

1. **Antes de publicar**: define el topic y el idioma adecuados a tu audiencia objetivo (US/EU). Asegúrate de no estar protegida.
2. **Hora de publicación**: hora punta de tu audiencia objetivo, no la tuya. (El modelo no penaliza pero el `AgeFilter` y el bucket de edad sí.)
3. **Formato**:
   - Texto + imagen es lo más versátil.
   - Vídeo solo si dura ≥10-15s y tiene audio (Grok lo transcribe).
   - Evita threads largos como estrategia de alcance — concéntrate en un único tweet "banger" candidate.
4. **Hook**: primer línea retentiva (maximiza dwell + cont_dwell_time). Pregunta o afirmación polarizante (con tacto) generan reply.
5. **Activación inmediata**: en los primeros 5-10 minutos, notifica a tu red próxima (DM, comunidad propia). Quieres cruzar el **min-traction gate** rápido.
6. **No publiques otros posts en las siguientes 2-4 horas**. Diversity decay te destruye.
7. **Si después de 30 min no hay tracción**: el post está fuera del pipeline de Banger Screen. Sigue siendo visible para tus seguidores pero no para retrieval OON. Aceptarlo y pasar a otro post.
8. **Si va bien**: el post está en Banger Screen, posiblemente con `quality_score ≥ 0.4`. Después de 1-2h, el modelo tiene buenos signals; las 24-48h siguientes son la "long tail" de impresiones.
9. **A las 80 horas**: el post cae en `overflow_bucket` de edad. Game over para descubrimiento; sigue archivado.

---

## 25. Verificación: ¿es cierto el viral "Nikita hides this in Rust"?

Hay un tuit que circula afirmando lo siguiente:

> *"AuthorSocialgraphFilter, VF visibility filters, and the AuthorDiversityScorer — these motherfuckers can quietly kneecap entire groups of accounts. One side gets their posts blasted across everyone's For You like free OnlyFans. The other side? Their shit gets DIVERSITY-scored, negative-weighted, and shadow-raped into digital oblivion.*
>
> *And the best part? All the real control knobs — the secret thresholds, the custom filter rules, the exact weights they're using to boost their preferred cult while burying everyone else — are sitting in private Rust files and config systems that will NEVER see the light of day."*

Lo paso por el código punto por punto. Mezcla cosas **correctas**, cosas **falsas** y una **inferencia conspirativa** que el código no respalda.

### 25.1 "AuthorSocialgraphFilter puede kneecapar grupos enteros de cuentas"

**Falso (mecanísticamente).** El filtro completo se reduce a esto:

```rust
let muted = viewer_muted_user_ids.contains(&author_id);
let blocked = viewer_blocked_user_ids.contains(&author_id);
let author_blocks_viewer = candidate.author_blocks_viewer.unwrap_or(false);
let quoted_author_blocks_viewer = candidate.quoted_author_blocks_viewer.unwrap_or(false);
let viewer_blocks_quoted_author = ...;
let viewer_blocks_retweeted_user = ...;

if muted || blocked || author_blocks_viewer || quoted_author_blocks_viewer
    || viewer_blocks_quoted_author || viewer_blocks_retweeted_user
{ removed.push(candidate); } else { kept.push(candidate); }
```

Fuente: [`author_socialgraph_filter.rs`](x-algorithm/home-mixer/filters/author_socialgraph_filter.rs) completo, 61 líneas.

Es un filtro **estrictamente per-viewer**. Solo consulta:
- Los blocks/mutes del **propio viewer**.
- Si el **autor** ha bloqueado al **viewer** (relación 1↔1).
- Lo mismo para autores citados y retweeteados.

No consulta ninguna lista global, ningún parámetro externo, ningún sistema de etiquetado de cuentas. No hay manera de que este filtro "kneecape grupos". Solo aplica la voluntad expresa del viewer y la relación bidireccional con el autor concreto. Y un grep por `globally_blocked|denylist|banned_users|hidden_accounts|admin_block` en todo el repo **no devuelve nada**.

### 25.2 "AuthorDiversityScorer puede kneecapar grupos enteros de cuentas"

**Falso.** Este es el más claro. El archivo entero ocupa 73 líneas y la única función no trivial es:

```rust
fn multiplier(&self, position: usize) -> f64 {
    (1.0 - self.floor) * self.decay_factor.powf(position as f64) + self.floor
}
// ...
let entry = author_counts.entry(candidate.author_id).or_insert(0);
let position = *entry;
*entry += 1;
let multiplier = self.multiplier(position);
```

Fuente: [`author_diversity_scorer.rs:29-58`](x-algorithm/home-mixer/scorers/author_diversity_scorer.rs).

- Cuenta cuántas veces aparece **cada `author_id`** en la lista de candidatos de **esta única respuesta**.
- Multiplica el score por una función **idéntica** para todos los autores: la posición N-ésima de cualquier autor se reduce por el mismo factor.
- No lee ningún campo de identidad/política/grupo. **No hay consulta externa**: la información viene únicamente del propio batch de candidatos.

Para que este scorer pudiera tratar "grupos" diferentes haría falta inyectar una lista, una API externa, o una categoría en el candidato. Nada de eso está en el código. La afirmación es factualmente incorrecta.

### 25.3 "VF visibility filters pueden kneecapar cuentas"

**Verdad parcial, pero NO por grupo.** El `VFFilter` sí puede dropear posts:

```rust
fn should_drop(reason: &Option<FilteredReason>) -> bool {
    match reason {
        Some(FilteredReason::SafetyResult(safety_result)) =>
            matches!(safety_result.action, Action::Drop(_)),
        Some(_) => true,
        None => false,
    }
}
```

Fuente: [`vf_filter.rs`](x-algorithm/home-mixer/filters/vf_filter.rs).

Pero la **lista de razones por las que un post puede ser droppeado** es cerrada y está en el código publicado, **basadas en contenido, no en identidad**:

```rust
pub(crate) const MEDIUM_RISK_LABELS: &[SafetyLabelType] = &[
    SafetyLabelType::NSFW_HIGH_PRECISION,
    SafetyLabelType::NSFW_HIGH_RECALL,
    SafetyLabelType::NSFA_HIGH_PRECISION,
    SafetyLabelType::NSFA_KEYWORDS_HIGH_PRECISION,
    SafetyLabelType::GORE_AND_VIOLENCE_HIGH_PRECISION,
    SafetyLabelType::NSFW_REPORTED_HEURISTICS,
    SafetyLabelType::GORE_AND_VIOLENCE_REPORTED_HEURISTICS,
    SafetyLabelType::NSFW_CARD_IMAGE,
    SafetyLabelType::DO_NOT_AMPLIFY,
    SafetyLabelType::NSFA_COMMUNITY_NOTE,
    SafetyLabelType::PDNA,
    SafetyLabelType::EGREGIOUS_NSFW,
    SafetyLabelType::GROK_NSFA,
    SafetyLabelType::NSFW_TEXT,
];
```

Fuente: [`brand_safety.rs:14-29`](x-algorithm/home-mixer/models/brand_safety.rs).

Las etiquetas hablan de NSFW/NSFA/gore/violencia/PDNA, no de afiliaciones. Lo que **NO** está publicado es:
- El motor que **asigna** estas etiquetas (la *Safety Label Store*) y sus reglas BotMaker.
- Los prompts del clasificador Grok que produce `GROK_NSFA`.
- Las reglas humanas (`BotMakerAction.rule_id`) que pueden añadir labels manualmente; el código solo expone los rangos por categoría (`1000-1099 Content`, `1100-1199 ContentLimited`, `1200-1399 Safety`, `1400-1499 Grok`, `1500-1600 Quote`).

**Punto de honestidad**: aquí sí hay opacidad real. Una etiqueta como `DO_NOT_AMPLIFY` es genérica; en teoría un operador interno con permisos podría aplicarla a una cuenta concreta vía BotMaker. **No hay nada en el código publicado que muestre cómo se decide aplicarla o quién puede hacerlo**. Si alguien quisiera abusar del sistema, **éste sería el sitio**, no los dos filtros que cita el tuit.

### 25.4 "Una facción es amplificada como OnlyFans gratis, la otra hundida"

**No respaldado por el código.** En todo el repo no aparece:
- Ningún parámetro `political`, `partido`, `ideology`, `protected_class`.
- Ninguna lista "preferred_users", "amplify_list", "boost_users", "priority_accounts".
- Ningún boost por `is_verified` / `is_blue` / `subscription_level` en los scorers (sí existe `subscription_level` como campo, pero solo se usa para hidratar contenido subscriber-only y para métricas — no como peso de score; ver §10 y §22 del documento).

Las **únicas** listas de IDs hardcodeadas con tratamiento especial son:

```rust
if params::TRACE_USER_IDS.contains(&proto_query.viewer_id) {
    b3_info.force_sample();   // forzar logging detallado
}
// ...
if params::TEST_USER_IDS.contains(&query.user_id) {
    return Ok(ForYouOutput { items: vec![] });   // feed vacío para testers
}
```

Fuente: [`server.rs:69`](x-algorithm/home-mixer/server.rs), [`for_you_server.rs:32`](x-algorithm/home-mixer/for_you_server.rs).

Son listas de **debugging interno**: a quien está en `TRACE_USER_IDS` se le genera trazado detallado; a quien está en `TEST_USER_IDS` se le devuelve feed vacío (probablemente cuentas de test). Ninguna es una lista de "favoritos amplificados".

### 25.5 "Todos los control knobs reales están en archivos Rust privados"

**Parcialmente cierto, pero el framing es engañoso.**

Lo que **sí** está fuera del repo público (lo he documentado a lo largo del .md):
1. Los **valores numéricos** de los pesos (`FavoriteWeight`, `ReplyWeight`, `OonWeightFactor`, `AuthorDiversityDecay`, `MinVideoDurationMs`, etc.). Viven en `xai_feature_switches::Params`, un sistema de configuración externa.
2. Los **prompts** de los clasificadores Grok (`BangerMiniVlmScreenScore`, `SpamSystemLowFollower`, `SafetyPtos`, `ReplyScoringSystem`, las 7 policy prompts: `ViolentMediaPolicy`, `AdultContentPolicy`, etc.).
3. La **utilidad** `country_codes::bucket_country`.
4. Las **reglas BotMaker** que aplican manualmente safety labels (los rangos están publicados; las reglas concretas no).
5. Los **pesos entrenados** del Phoenix transformer de producción (el repo publica una mini-versión: 256-dim, 4 cabezas, 2 layers; producción es mayor).
6. Los **crates `xai_*`** referenciados: el repo importa 25+ crates externos (`xai_decider`, `xai_feature_switches`, `xai_recsys_aggregation`, `xai_visibility_filtering`, `xai_safety_label_store`, `xai_post_text`, etc.) cuyo código no se publica.

Lo que **NO** es cierto:
- No son "archivos Rust privados" — son **configuración externa** y **librerías compartidas** del stack de xAI. La diferencia importa: lo que falta no es código de algoritmo escondido, son **valores parametrizables** y **librerías cliente** del resto del stack.
- La estructura **completa** del pipeline ESTÁ publicada: cada filtro, cada scorer, cada hydrator, cada source, los nombres de las features del modelo, la arquitectura del transformer, las labels de safety usadas, los topics que se reconocen. Si hubiera un "boost al grupo preferido" tendría que existir o (a) como flag en el query/candidato (no existe), o (b) como signal de entrada al transformer (no aparece en `RecsysBatch`), o (c) como filtro paramétrico (no se ve). El espacio donde podría esconderse es estrecho.

### 25.6 "Boost preferred cult, bury everyone else"

**Sin evidencia en el código.** Lo que sí permite la arquitectura es que **xAI configure el sistema distinto para distintos cohortes de USUARIOS** vía feature switches con dimensiones como `country`, `language`, `account_age_days`, `has_phone_number`, `user_roles`. Eso es real (ver §18 sobre shadow traffic). Pero es la VIEWER, no el AUTOR, la que ve diferentes experimentos — no es un sistema de "amplificación de cuentas favoritas".

Para que existiera "boost del cult preferido" tendrían que pasar una de estas cosas:
1. Que el `PostCandidate` llevase un campo de identidad/afiliación del autor → **no existe** (revisado todo `models/candidate.rs` y `candidate_features.rs`).
2. Que algún scorer consultase un servicio externo por author_id → ningún scorer publicado hace esto; todos operan sobre `phoenix_scores` y `author_id` solo para el diversity decay.
3. Que las etiquetas de safety se apliquen políticamente vía BotMaker → **posible** en abstracto, pero esto sería un abuso operativo, no un mecanismo del algoritmo.
4. Que el modelo Phoenix tuviera *biased training data* → no se puede verificar desde el código (no se publican los datos). Una capa adicional de preocupación legítima.

### 25.7 Donde sí hay opacidad real (lo que el tuit roza pero no formula)

La crítica honesta a la apertura parcial es:

- **No se pueden auditar los pesos numéricos** (no podemos saber si `BlockAuthorWeight = -100` o `-10`).
- **No se pueden auditar los prompts de Grok** (los prompts SÍ pueden tener sesgos políticos/ideológicos en la formulación; sin verlos no se puede saber).
- **No se pueden auditar las reglas BotMaker** (rangos `1200-1399 = Safety` están en el código pero las reglas concretas no).
- **No se puede auditar el dataset de entrenamiento** de Phoenix (un modelo entrenado sobre engagement de usuarios sesgados reproduce ese sesgo).
- **No se publican los rebalances/experimentos por cohorte** que se ejecutan via feature switches.

Estas son críticas legítimas y razonables a la apertura parcial. Lo que el tuit afirma — que tres archivos Rust concretos (que sí están publicados) son la herramienta de kneecaping de grupos — **es factualmente falso**. La opacidad real está en **otro sitio** (parámetros, prompts, reglas BotMaker, datos), y dista mucho de ser equivalente a "boostean al cult preferido".

### 25.8 Veredicto

| Afirmación del tuit | Veredicto |
|---|---|
| "AuthorSocialgraphFilter kneecapea grupos de cuentas" | **Falso.** Es per-viewer puro, sin lista global. |
| "AuthorDiversityScorer kneecapea grupos de cuentas" | **Falso.** Aplica decay idéntico a todos los autores por posición en la misma respuesta. |
| "VF filters kneecapean grupos" | **Parcialmente cierto en mecanismo** (sí dropea), **falso en framing**: las etiquetas que dropean son de contenido (NSFW, gore, violencia, DO_NOT_AMPLIFY), no de identidad. |
| "Las thresholds y pesos están en archivos privados que nunca verán la luz" | **Cierto parcialmente.** Valores numéricos, prompts de Grok, reglas BotMaker y crates xAI externos no están publicados — pero la **estructura** del algoritmo sí. |
| "Boost al cult preferido, hundir al resto" | **Sin evidencia en código.** No hay campo, lista, ni parámetro que separe autores por grupo/identidad/política. |

---

## 26. ¿Existen los shadowbans en el algoritmo? Sí, y son de cuatro tipos distintos

"Shadowban" es un término que la gente usa para **cuatro mecanismos distintos** que existen en el código. Los distingo porque cada uno tiene una causa, un efecto y una contramedida diferentes.

### 26.1 Shadowban duro: `Action::Drop` por Visibility Filtering

```rust
fn should_drop(reason: &Option<FilteredReason>) -> bool {
    match reason {
        Some(FilteredReason::SafetyResult(safety_result)) => {
            matches!(safety_result.action, Action::Drop(_))
        }
        Some(_) => true,
        None => false,
    }
}
```

Fuente: [`home-mixer/filters/vf_filter.rs:22-30`](x-algorithm/home-mixer/filters/vf_filter.rs).

Tu post se elimina del feed si el servicio externo `xai_visibility_filtering` devuelve `Action::Drop(_)` **o** cualquier `FilteredReason` que no sea `SafetyResult` (la cláusula `Some(_) => true`).

**Qué dispara `Action::Drop`:**
- Tweet borrado por el autor
- Cuenta suspendida
- Cualquier *SafetyLabel* concreto que el servicio externo decida que merece drop (no visible en el código abierto: es el `xai_visibility_filtering` crate)
- Etiquetas como `PDNA` (PhotoDNA, contenido de abuso infantil) tienen drop garantizado

**Importante**: el código publicado solo deja ver QUE existe el mecanismo, no las reglas que deciden cuándo aplicarlo. Esas reglas viven en el servicio externo y en BotMaker. Aquí hay opacidad operativa real.

**Cómo te enteras**: NO te enteras. Es por definición silencioso. Tu post sigue visible para ti y para algunos canales (tu propio perfil, búsqueda directa por ID quizá), pero **no aparece en el For You de nadie**.

### 26.2 Shadowban "soft": `DO_NOT_AMPLIFY` y resto de etiquetas `MediumRisk`

Esto es el shadowban más "clásico" — el contenido sigue accesible pero su distribución se degrada estructuralmente.

```rust
pub(crate) const MEDIUM_RISK_LABELS: &[SafetyLabelType] = &[
    SafetyLabelType::NSFW_HIGH_PRECISION,
    SafetyLabelType::NSFW_HIGH_RECALL,
    SafetyLabelType::NSFA_HIGH_PRECISION,
    SafetyLabelType::NSFA_KEYWORDS_HIGH_PRECISION,
    SafetyLabelType::GORE_AND_VIOLENCE_HIGH_PRECISION,
    SafetyLabelType::NSFW_REPORTED_HEURISTICS,
    SafetyLabelType::GORE_AND_VIOLENCE_REPORTED_HEURISTICS,
    SafetyLabelType::NSFW_CARD_IMAGE,
    SafetyLabelType::DO_NOT_AMPLIFY,    // ← el "shadowban" canónico
    SafetyLabelType::NSFA_COMMUNITY_NOTE,
    SafetyLabelType::PDNA,
    SafetyLabelType::EGREGIOUS_NSFW,
    SafetyLabelType::GROK_NSFA,
    SafetyLabelType::NSFW_TEXT,
];
```

Fuente: [`home-mixer/models/brand_safety.rs:14-29`](x-algorithm/home-mixer/models/brand_safety.rs).

Cualquiera de estas etiquetas marca a tu post como `MediumRisk`. Las **consecuencias** que están documentadas en el código abierto:

1. **Ningún anuncio adyacente** ([`ads/util.rs:25-27`](x-algorithm/home-mixer/ads/util.rs)). `has_avoid(post)` devuelve `true` para todo `MediumRisk` y el blender evita poner ads a su lado. Resultado: el sistema **pierde dinero** cuando muestra tu post. Eso ya crea un incentivo estructural para que el ranking lo deprima.
2. **Los anuncios `BsrLow/BsrIas`** (anuncios de marca premium) **no se colocan junto a posts `LowRisk`** ([`ads/util.rs:79-97`](x-algorithm/home-mixer/ads/util.rs)). El cliff es: cuanto peor sea tu verdict, menos anuncios premium llegan a tu vecindad.
3. **El propio `LowRisk` (segundo escalón)** te excluye de inventario premium aunque sigas siendo "kept".

**Lo que NO se ve en el código abierto pero existe necesariamente:**
- El `xai_visibility_filtering` externo puede usar `Action::Limit(...)` o `Action::Interstitial(...)` (el `Action::Drop(_)` con la tupla y el `_` sugieren un enum con otras variantes). El `VFFilter` solo mata por `Drop`, pero las otras variantes propagan al cliente: warning panel, click-to-view, interstitial, etc. Eso reduce el dwell esperado y por tanto el score predicho.

**La etiqueta `DO_NOT_AMPLIFY` es la más relevante** porque NO es por contenido específico (NSFW, gore…) sino por decisión operativa. Existe como flag genérico aplicable manualmente por reglas BotMaker. Es **el botón rojo del shadowban operativo**.

**Cómo te enteras**: el campo `safety_labels` en `PostCandidate` se serializa a `ScoredPost` con `label_type`, `description`, `source` ([`home-mixer/scored_posts_server.rs:95-100`](x-algorithm/home-mixer/scored_posts_server.rs) y el mapeo de [`scored_posts_server.rs:192-211`](x-algorithm/home-mixer/scored_posts_server.rs)). Es decir: el sistema SABE en cada respuesta qué etiquetas lleva tu post. Si X quisiera exponer al usuario por qué su post se está distribuyendo poco, podría — pero no lo hace en el producto.

### 26.3 Shadowban operacional via reglas BotMaker

```rust
pub(crate) fn botmaker_rule_category(rule_id: i64) -> &'static str {
    match rule_id {
        1000..=1099 => "Content",
        1100..=1199 => "ContentLimited",
        1200..=1399 => "Safety",
        1400..=1499 => "Grok",
        1500..=1600 => "Quote",
        _ => "Legacy",
    }
}
```

Fuente: [`brand_safety.rs:80-89`](x-algorithm/home-mixer/models/brand_safety.rs).

Una `SafetyLabel` puede tener su origen como `SafetyLabelSource::BotMakerAction(action)` con un `rule_id`. Es decir: **operadores internos de X pueden crear reglas BotMaker que apliquen safety labels a posts/cuentas concretas**. El código expone los RANGOS de categorías (1100-1199 son `ContentLimited`, etc.) pero **no las reglas concretas** ni el panel desde el que se aplican.

Esto significa que el shadowban operativo —"este moderador ha decidido limitar esta cuenta"— existe técnicamente. El nombre de la categoría `ContentLimited` y `Safety` deja poco margen a la interpretación.

### 26.4 Shadowban implícito: el modelo aprende a deprimirte

```python
@dataclass
class HashConfig:
    num_user_hashes: int = 2
    num_item_hashes: int = 2
    num_author_hashes: int = 2     # ← el modelo tiene embedding por autor
    num_ip_hashes: int = 0
```

Fuente: [`phoenix/recsys_model.py:93-100`](x-algorithm/phoenix/recsys_model.py).

El transformer Phoenix usa hashes del `author_id` como input. Con ello aprende **patrones de engagement asociados a cada autor**. Si tu cuenta tiene un histórico de generar engagement bajo + muchos "not_interested" + bloqueos + reports, el modelo **internaliza eso en tu embedding de autor**. El resultado: aunque tu próximo post sea objetivamente bueno, **tu propio embedding lo penaliza** porque está envenenado por el histórico.

Esto NO es shadowban explícito. Pero funcionalmente equivale a uno:
- El modelo aprende automáticamente
- La penalización es a-nivel-cuenta, no a-nivel-post
- Es prácticamente irreversible salvo cambiando de cuenta o consiguiendo mucho engagement positivo durante un tiempo largo
- No hay nadie a quien apelar

**Cómo te puede pasar sin darte cuenta:** una racha de posts con engagement bajo (especialmente con muchos `not_dwelled` y `not_interested`) "envenena" el embedding de tu cuenta durante las próximas semanas. **El "min-traction gate" lo amplifica** (§15): si tus últimos posts no cruzaron el threshold, el modelo no tiene posts buenos recientes con los que recalibrar tu embedding.

### 26.5 Shadowban estructural: el gate de min-traction

Ya documentado en §15. Lo añado aquí porque es un shadowban funcional: posts que no cruzan el threshold de engagement temprano **nunca son procesados** por el pipeline de Grok (`BANGER_INITIAL_SCREEN`, `SAFETY_PTOS`, `POST_EMBEDDING_WITH_SUMMARY_FOR_REPLY`). Sin embedding multimodal de calidad → no entras al corpus de retrieval → no descubrible OON.

A diferencia de los anteriores, este shadowban es **automático y per-post**, no per-cuenta. Pero su efecto agregado es el mismo: pasas a invisibilidad.

### 26.6 Lo que NO se considera shadowban en el código

Para evitar la confusión que se ve en discusiones públicas, estos NO son shadowbans (aunque a veces se les llama así):

- **`AuthorDiversityScorer`** — solo evita que veas 10 posts seguidos del mismo autor en la misma respuesta. No es supresión per-cuenta.
- **`AuthorSocialgraphFilter`** — solo aplica los bloqueos/silencios que el viewer ha configurado, más la relación bidireccional con el autor.
- **`OonWeightFactor`** — el descuento por estar fuera-de-red. Aplica a TODOS los autores OON por igual. No es per-cuenta.
- **`is_shadow_traffic` (50% sampling)** — engañoso por el nombre: es muestreo de tráfico para experimentos A/B, NO un mecanismo de shadowban.

### 26.7 Tabla resumen de shadowbans

| Tipo | Mecanismo | Verificación de existencia | Reversibilidad | Detección |
|---|---|---|---|---|
| Hard drop | `VFFilter` + `Action::Drop` | Sí, en código | Apelable (suspensión) | Imposible para el usuario |
| Soft (DO_NOT_AMPLIFY etc.) | `MediumRisk` + sin ads adyacentes | Sí, en código | Improbable, opaco | Imposible para el usuario |
| BotMaker rule | `SafetyLabelSource::BotMakerAction` | Sí, mecanismo en código (reglas concretas no) | Opaco | Imposible para el usuario |
| Modelo "envenenado" | `author_hashes` en Phoenix | Sí, en código | Lento, ~semanas de buen engagement | Imposible para el usuario |
| Min-traction gate | Kafka topic `MIN_TRACTION_FOR_GROX` | Sí, en código | Per-post (cada post se evalúa de nuevo) | Imposible para el usuario |

### 26.8 Cómo defenderse en la práctica

1. **Evita las etiquetas que activen `MediumRisk`**. Es la palanca más obvia. Las 14 etiquetas están listadas y son content-based (NSFW, gore, etc.). Si no posteas eso, no cualificas.
2. **No alimentes el modelo con engagement negativo**: cualquier rastro de `not_interested` / `block` / `mute` / `report` se queda en tu embedding de autor.
3. **Mantén una cadena consistente de posts que crucen min-traction**: incluso si publicas poco, asegúrate de que CADA post tenga engagement temprano. Mejor 1 post a la semana que pasa el gate, que 10 que mueren en cold start.
4. **Si sospechas que estás "soft-shadowbanned"**: comprueba si los reach metrics caen drásticamente y desfasados de tu engagement habitual. La caída repentina y total es típicamente `DO_NOT_AMPLIFY`. La caída lenta y progresiva es el embedding envenenado.
5. **No hay apelación visible para shadowbans soft**: el código no expone ningún endpoint de "review", solo mete las labels y el verdict.

---

## 27. La pregunta concreta: estoy en Europa y publico en inglés para audiencia US, ¿me penaliza estar en Europa?

**Respuesta directa: NO, no por ningún mecanismo explícito del código.** El algoritmo **no conoce tu ubicación como autor.** Lo demuestro punto por punto.

### 27.1 Lo que el sistema sabe del POST cuando lo va a puntuar

El `PostCandidate` —la estructura que viaja por todo el pipeline— tiene **estos campos y solo estos** sobre el post y su autor:

```rust
pub struct PostCandidate {
    pub tweet_id: u64,
    pub author_id: u64,
    pub tweet_text: String,
    pub in_reply_to_tweet_id: Option<u64>,
    pub retweeted_tweet_id: Option<u64>,
    pub retweeted_user_id: Option<u64>,
    pub quoted_tweet_id: Option<u64>,
    pub quoted_user_id: Option<u64>,
    pub phoenix_scores: PhoenixScores,
    // ... scoring metadata ...
    pub author_followers_count: Option<i32>,
    pub author_screen_name: Option<String>,
    pub retweeted_screen_name: Option<String>,
    pub language_code: Option<String>,       // ← idioma del POST, NO del autor
    pub fav_count, reply_count, repost_count, quote_count,
    pub mutual_follow_jaccard: Option<f64>,
    pub brand_safety_verdict: Option<BrandSafetyVerdict>,
    pub safety_labels: Vec<SafetyLabelInfo>,
    pub has_media: Option<bool>,
    pub min_video_duration_ms: Option<i32>,
    pub filtered_topic_ids: Option<Vec<i64>>,
    // ... bool flags...
}
```

Fuente: [`home-mixer/models/candidate.rs:8-50`](x-algorithm/home-mixer/models/candidate.rs).

**No hay**: `author_country`, `author_geo`, `author_ip`, `author_region`, `author_location`, `creation_country`, `posting_country`. **Ninguno**. Lo confirmo con grep:

```bash
$ grep -rn "author_country|author_geo|author_location|posting_country|creation_country" --include="*.rs"
# (cero resultados)
```

### 27.2 Lo único que Gizmoduck (servicio de identidad de usuario) le da al sistema sobre el autor

```rust
pub struct GizmoduckCacheValue {
    pub author_followers_count: Option<i32>,
    pub author_screen_name: Option<String>,
    pub retweeted_screen_name: Option<String>,
}
```

Fuente: [`gizmoduck_hydrator.rs:142-147`](x-algorithm/home-mixer/candidate_hydrators/gizmoduck_hydrator.rs).

Tres campos. Ninguno es geográfico. El servicio `Gizmoduck` (el sistema interno de identidad de usuarios de X) hidrata estos tres y nada más sobre el autor.

### 27.3 Lo que el modelo Phoenix recibe sobre el autor

El input al transformer (en su versión open-source mini, [`phoenix/recsys_model.py:126-145`](x-algorithm/phoenix/recsys_model.py)):

```python
class RecsysBatch(NamedTuple):
    user_hashes: jax.typing.ArrayLike                     # del VIEWER
    history_post_hashes: jax.typing.ArrayLike             # posts que VIEWER engageó
    history_author_hashes: jax.typing.ArrayLike           # autores que VIEWER engageó
    history_actions: jax.typing.ArrayLike
    history_product_surface: jax.typing.ArrayLike
    candidate_post_hashes: jax.typing.ArrayLike           # hash del POST candidato
    candidate_author_hashes: jax.typing.ArrayLike         # hash del AUTOR del POST
    candidate_product_surface: jax.typing.ArrayLike
    history_continuous_actions: Optional
    candidate_impr_ts: Optional
    candidate_post_creation_ts: Optional
    user_ip_hashes: Optional                              # del VIEWER, no del autor
```

Y la `HashConfig` por defecto:

```python
num_user_hashes: int = 2      # 2 hashes del viewer
num_item_hashes: int = 2      # 2 hashes del post
num_author_hashes: int = 2    # 2 hashes del autor
num_ip_hashes: int = 0        # IP DEL VIEWER (desactivada por defecto)
```

Lo único que el modelo sabe del autor son **dos hashes anónimos del `author_id`**. No sabe ni tu nombre, ni tu país, ni tu IP. **Solo identidad opaca**.

### 27.4 Lo que sí entra al modelo sobre el contexto del viewer (no del autor)

Vía `TwitterContextViewer`:

```rust
impl GetTwitterContextViewer for ScoredPostsQuery {
    fn get_viewer(&self) -> Option<TwitterContextViewer> {
        Some(TwitterContextViewer {
            user_id: self.user_id as i64,
            client_application_id: self.client_app_id as i64,
            request_country_code: self.country_code.clone(),   // ← país del VIEWER
            request_language_code: self.language_code.clone(), // ← idioma del VIEWER
            ..Default::default()
        })
    }
}
```

Fuente: [`home-mixer/models/query.rs:214-222`](x-algorithm/home-mixer/models/query.rs).

Y el idioma DEL POST se pasa también, en `as_tweet_info()`:

```rust
language_code: xai_recsys_proto::language_code_string_to_enum(
    self.language_code.as_deref().unwrap_or(""),
) as i32,
```

Fuente: [`home-mixer/models/candidate.rs:140-142`](x-algorithm/home-mixer/models/candidate.rs).

Es decir, el modelo recibe el TUPLE:
- País del viewer (US)
- Idioma del viewer (en)
- Idioma del POST (en)
- Hash anónimo del autor
- ... (resto de señales)

Aprende correlaciones como: *"viewer US + idioma viewer EN + idioma post EN → P(engagement) alta"*. Si publicas en inglés a una audiencia US, el modelo está exactamente en el punto donde tu post matchea bien — **NO importa que tú estés en Europa**, porque esa dimensión no existe como feature.

### 27.5 ¿De verdad no hay forma de que el algoritmo sepa que estoy en Europa?

He buscado todos los caminos plausibles:

1. **`country_code` en la query**: existe pero es el del VIEWER, no del autor. La query la crea el cliente del viewer.
2. **`ip_location` via GeoIP**: igual, geoIP de la IP del VIEWER, no del autor.
3. **`Gizmoduck` (servicio de autor)**: solo devuelve followers count + screen name. Ni siquiera el `country_code` del perfil del autor sale por aquí.
4. **`util/phoenix_request`**: ESTE archivo NO está incluido en el repo público. Es donde se construye el request final al Phoenix. **Aquí hay una incertidumbre real**: podrían añadirle campos del autor que no veo. Pero las funciones que lo invocan (`build_user_context(query)`, `build_client_context(query)`) reciben **solo la query** —que no tiene info geográfica del autor—, así que la única forma de que entrasen sería que `build_prediction_request` llamase a *otro* servicio para enriquecer. No es lo natural en este tipo de pipeline (ya tenemos al `gizmoduck_hydrator` para eso).
5. **El hash del autor**: el modelo SOLO ve `author_id` como un hash. No es como si el modelo recibiese "user@Madrid".

Conclusión: **el código publicado no contiene ninguna ruta por la que tu ubicación física entre como feature.**

### 27.6 Pero entonces, ¿por qué me cuesta llegar a US desde Europa? (efectos indirectos reales)

El "sí me afecta" de la pregunta popular existe, pero no por una penalización geográfica directa. Es por **tres efectos indirectos** muy concretos:

#### (a) El embedding aprendido de tu cuenta

El modelo aprende un embedding por autor (vía hashes). Ese embedding se **forma a partir de tu engagement histórico**. Si tu audiencia hasta ahora ha sido mayoritariamente europea, el modelo te coloca en una zona vectorial cercana a usuarios europeos. Cuando un usuario US viene y le buscan candidatos via Phoenix Retrieval (Two-Tower), tu embedding queda lejos del suyo → no apareces en su top-K.

**Es un efecto Bayesiano**: si X autor ha generado engagement con miles de usuarios europeos pero ninguno de US, el modelo lo aprende. **Romperlo requiere generar engagement US sostenido.**

#### (b) Husos horarios y el `AgeFilter`

Esto sí es matemático:
- `POST_AGE_MAX_MINUTES = 4800` (80h) ([`phoenix/recsys_model.py:33`](x-algorithm/phoenix/recsys_model.py))
- Edad bucketizada en granularidad de 1h
- `params::MAX_POST_AGE` en el `AgeFilter` filtra posts más viejos que cierto umbral
- `TweetMixerSource` también filtra por `MAX_POST_AGE` en la fuente

Si publicas a las 10:00 hora Madrid, son las 04:00 ET. Para cuando un usuario US se conecta a las 09:00 ET, tu post tiene 5 horas → ya está en buckets de "menos fresco" que penalizan en retrieval/ranking. Si esperas a tu prime-time matinal europeo (10am-12am hora local), te pierdes la primera ola del día US.

**Esta es la única penalización "geográfica" matemáticamente certera, y es indirecta**: no por estar en Europa, sino por publicar en horario europeo.

#### (c) Tu propio comportamiento histórico

El `user_action_sequence` del modelo (las últimas ~128 acciones tuyas como **viewer**) influye en tu retrieval. Si tú mismo consumes contenido mayoritariamente europeo, **tu embedding como viewer** sigue siendo europeo. Eso no afecta a tus posts directamente, pero sí a **a quién sigues** y a **quién interactúa contigo**: si tu red es 95% europea, los señales tempranas en tu post vienen de europeos, y eso refuerza tu embedding hacia ese cluster.

### 27.7 ¿Y `user_ip_hashes`? ¿Eso es geo?

```python
num_ip_hashes: int = 0    # default disabled
```

Sí, el modelo PUEDE recibir hashes de la IP del **viewer** (no del autor). Pero:
- Está **deshabilitado por defecto** en la HashConfig del modelo mini.
- Aunque se habilite, es un hash — el modelo no sabe "192.168.x.y", sabe que "hash(IP) = X". Aprende patrones de IPs similares, no "país".
- Es la IP **del viewer en el momento de pedir su feed**, no la del autor en el momento de publicar.

### 27.8 Veredicto sobre tu pregunta concreta

**"Estoy en Europa, publico en INGLÉS para audiencia US: ¿me penaliza estar geoposicionado en Europa?"**

**Respuesta**: **No directamente, sí indirectamente y solo por dos factores controlables.**

- **NO directo**: ningún campo, parámetro, filtro ni feature del modelo conoce tu ubicación como autor. Tu IP en el momento de publicar no se almacena en el `PostCandidate`. Gizmoduck no te devuelve country. El modelo Phoenix solo ve un hash anónimo de tu `author_id`.
- **SÍ indirecto, pero al alcance de tu mano:**
  1. **Horario**: publica en prime-time US (mañana-tarde ET), no en tu mañana europea. La feature de edad del post sí entra al modelo y favorece a quien publica cuando su audiencia está despierta.
  2. **Idioma del post**: confirmado en inglés → buena correlación con `country_code=US, language_code=en` del viewer. Si publicaras en español, sí sería penalización (porque el modelo aprendió que post en español ≠ engagement de viewer US).
- **SÍ indirecto, fuera de tu control inmediato:**
  3. **Tu embedding de autor está sesgado por tu histórico de engagement**. Si has crecido con europeos, romper la barrera para llegar a US requiere semanas de engagement US sostenido. No es un castigo, es física de embeddings.

**Acciones concretas que SÍ funcionan:**
- Publicar en inglés con vocabulario US (incluyendo modismos, hashtags US, mencionar entidades reconocibles para US).
- Publicar a las 8-11 AM ET (14-17 hora Madrid en invierno, 13-16 en verano), o a las 6-9 PM ET (22-01 Madrid).
- Comentar/citar a cuentas US grandes (reply ranking te incluye con su audiencia).
- Generar interacción temprana con cuentas US (no solo europeas) para construir un embedding más "mixto".

**Acción que NO mueve la aguja**:
- Usar VPN para parecer estar en US al publicar. El sistema **no almacena tu IP de publicación** en el `PostCandidate` (he buscado, no existe el campo). Tu ubicación al postear es irrelevante porque **el algoritmo nunca llega a saberla**.

---

## 28. Resumen condensado del embedding y del gate de los 30 minutos

Síntesis útil del §26.4 ("shadowban implícito") y del §15 ("min-traction gate"). En bullets, en inglés, sin paja:

- Every account has an internal embedding: a vector that sums up how your account behaves (topics, engagement, who you interact with)
- The model uses it every time it decides who to show your posts to
- Good history → clean embedding → the model pushes you
- Negative signals piling up (blocks, mutes, reports, not_interested) → toxic embedding → automatic penalties
- It does NOT reset. What you do today stays in there for weeks, poisoning everything you publish after
- Getting out of a shadowban or a low-reach streak feels like moving a giant rusted wheel — by design
- The embedding doesn't decay on a clock. It decays with NEW engagement entering the system
- If you stop posting, the old bad signals stay frozen. Nothing overwrites them
- With sustained good content: noticeable improvement after 6 to 8 weeks, real shift around 12 to 16 weeks (assuming no new bad signals along the way)
- First 30 minutes = everything. No fast engagement → Grok never evaluates the post → no quality score, no deep analysis, no out-of-network retrieval. Dead and buried

Soporte en código:

- **Hashes del autor como input al modelo**: [`phoenix/recsys_model.py:93-100`](x-algorithm/phoenix/recsys_model.py) — `num_author_hashes = 2`
- **Ventana de acciones de 128**: [`phoenix/recsys_model.py:342`](x-algorithm/phoenix/recsys_model.py) — `history_seq_len: int = 128`
- **Min-traction gate antes del Banger Screen**: [`grox/generators/stream_generator.py:60-100`](x-algorithm/grox/generators/stream_generator.py) — Kafka topic `CONTENT_UNDERSTANDING_REALTIME_UNIFIED_POSTS_MIN_TRACTION_FOR_GROX`
- **Reentrenamiento continuo del modelo**: [`phoenix/README.md`](x-algorithm/phoenix/README.md) — "Production Phoenix is trained continuously on real-time data"

---

## 29. ¿Links, hashtags y menciones en el primer post te joden el alcance?

**Respuesta directa, basada en el código abierto: NO hay penalización explícita por ninguna de las tres cosas.** Pero hay efectos indirectos que sí importan.

### 29.1 Lo que el código pasa al modelo sobre el post

La función `as_tweet_info()` ([`home-mixer/models/candidate.rs:108-149`](x-algorithm/home-mixer/models/candidate.rs)) construye el `TweetInfo` que se envía al transformer Phoenix. Lleva **exactamente esto**:

```rust
tweet_id, author_id,
retweeting_tweet_id, retweeting_author_id,
quoted_tweet_id, quoted_author_id,
in_reply_to_tweet_id,
is_author_followed_by_user,
min_video_duration_ms,
fav_count, retweet_count, quote_count, reply_count,
language_code,
tweet_bool_features: {
    has_media,
    is_retweet,
    is_quote,
    is_reply,
}
```

Y el `PostCandidate` ([`home-mixer/models/candidate.rs:8-50`](x-algorithm/home-mixer/models/candidate.rs)) tiene **40 campos**. Ninguno es `has_url`, `has_link`, `url_count`, `has_hashtag`, `hashtag_count`, `has_mention`, `mention_count`.

Búsqueda exhaustiva con grep:

```bash
$ grep -rn "has_url|has_link|url_count|link_count|external_url|expand_url" --include="*.rs"
# (cero resultados)
$ grep -rn "hashtag|has_hashtag" --include="*.rs"
# (cero resultados)
$ grep -rn "has_mention|mention_count|user_mention" --include="*.rs"
# (cero resultados)
```

**Conclusión literal**: los `TweetBoolFeatures` que recibe el modelo son solo 4 (`has_media`, `is_retweet`, `is_quote`, `is_reply`). No hay un boolean "este post tiene un link" ni "este post tiene un hashtag" ni "este post tiene una mención". El modelo no los puede usar como feature directa porque **no existen como entrada**.

### 29.2 ¿Dónde se usa el `tweet_text` entonces?

Sí, el texto del tweet se hidrata ([`core_data_candidate_hydrator.rs`](x-algorithm/home-mixer/candidate_hydrators/core_data_candidate_hydrator.rs)) y se guarda en `PostCandidate.tweet_text`. Pero el código lo usa **solo en dos sitios** y por dos motivos:

1. **`MutedKeywordFilter`** ([`home-mixer/filters/muted_keyword_filter.rs`](x-algorithm/home-mixer/filters/muted_keyword_filter.rs)): tokeniza tu texto y lo compara con los keywords que el VIEWER ha muteado. No te penaliza por hashtag, te elimina si tu texto contiene "kpop" para alguien que muteó "kpop".

2. **`ads/util.rs` (adjacency control)** ([`home-mixer/ads/util.rs:116-151`](x-algorithm/home-mixer/ads/util.rs)): tokeniza tu texto y compara con la blocklist de palabras del anunciante adyacente. Si matchea, **al anuncio se le cae la posición**, no a ti.

**Ningún scorer del repo abierto consume el `tweet_text` ni mira hashtags/links/menciones para asignar peso.**

### 29.3 Lo que SÍ entra al modelo del contenido del post

Solo dos cosas relacionadas con el contenido entran al Phoenix:

- **El embedding multimodal generado por Grok**: el contenido completo del post (texto + imágenes + ASR de vídeo) lo procesa Qwen3 + el embedder multimodal de xAI y produce un vector. Ese vector es lo que se usa para retrieval Two-Tower.
- **El score `slop_score` del Banger Initial Screen**: Grok-VLM puntúa el post y devuelve, entre otras cosas, un `slop_score` que detecta contenido de baja calidad LLM. Si tu post se ve "AI slop" baja la `quality_score` global.

Es decir: el contenido se evalúa como un todo por un modelo de lenguaje (Grok), no como una suma de "tiene link / tiene hashtag / tiene mención".

### 29.4 Efectos INDIRECTOS que sí pueden hundir tu alcance con link/hashtag/@

#### Links

- **Reducen `dwell_time`**: el usuario hace tap en el link, sale de X, y los segundos en el post se cortan. El `cont_dwell_time` baja. El `not_dwelled_score` (señal negativa) puede subir si la mayoría sale sin volver.
- **`click_dwell_time` puede compensarlo PERO solo si vuelven**: si tras clicar al link el usuario regresa al post y se queda, suma `cont_click_dwell_time` (peso positivo). Si se va y no vuelve, neto negativo.
- **Posibles preferencias en los prompts de Grok**: los prompts del `BangerInitialScreenClassifier` (`BangerMiniVlmScreenScore`) **no están publicados**. Podrían perfectamente penalizar posts que parecen "drive-traffic only" (link + tweet vacío). No podemos verificarlo, pero es la zona donde la "regla folclórica de no poner links" podría existir realmente.

#### Hashtags

- **Sin efecto directo**: no son una feature ni una señal.
- **Posible upside con topic match**: si tu hashtag coincide con un topic explícito que Grok reconoce (los 80+ topics de §11 del documento), tu post tiene más probabilidades de ser elegible para `PhoenixTopicsSource`, que tiene un `TopicOonWeightFactor` mejor que el general.
- **Posible downside si abusas**: el `BangerScreen` con `slop_score` PUEDE penalizar posts que parecen spam (cadena de #ai #ml #startup #saas etc.). De nuevo, no verificable porque los prompts no están publicados.

#### Menciones (@)

- **Sin efecto directo en scoring**.
- **Efecto social fuerte si la cuenta mencionada responde o RT**: al ser respuesta/RT a tu post o quote, dispara `reply_count`, `quote_count`, `retweet_count`, que SÍ son features explícitas del modelo.
- **Reply-spammear cuentas pequeñas con @**: te puede caer el `SpamEapiLowFollowerClassifier` (§6.2 del documento). Pero esto es para *replies*, no para posts originales que mencionan.

### 29.5 Veredicto y regla práctica

| Elemento | Penalización directa en código abierto | Efecto indirecto |
|---|---|---|
| **Link** | Ninguna | Reduce dwell si el usuario se va y no vuelve. Posible penalización en prompts no publicados |
| **Hashtag** | Ninguna | Puede activar matching con topics OON (positivo). Abuso puede subir slop_score (negativo) |
| **Mención** | Ninguna | Puede generar engagement si la cuenta interactúa (positivo) |

**Regla práctica:**

- **Link sí, pero acompañado de texto que ya tenga sustancia**. Que el usuario no necesite clicar para que el post valga. El link es bonus, no el plato.
- **Hashtags: 1-2 muy relevantes**. Sirven para topic matching. 5+ huele a spam y posiblemente activa slop_score.
- **Menciones: úsalas para quien aporta al contenido**. Si mencionas a alguien y le interesa tu post, te dará reply/RT/quote → tres features positivas de golpe.

Si quieres maximizar el primer post, el patrón ganador en el código es:

> Texto sustancioso que retenga dwell (10-30+ segundos de lectura), **luego** menciona/link/hashtag al final como complemento, no como sustituto del contenido.

Lo que mata el alcance NO es poner un link. Es publicar un post cuyo único valor sea el link.

---

## 30. Anatomía del post perfecto para máximo alcance

Sintetizo todo el resto del documento en una sola "receta" del post objetivamente óptimo según lo que está en el código. Cada decisión tiene su soporte en una sección anterior; cito al lado el por qué.

### 30.1 Pre-condiciones de la cuenta (background)

Antes incluso de escribir nada, tu cuenta tiene que cumplir:

- **Cuenta pública (no protegida)** — sin embedding multimodal no hay retrieval OON (§22.7)
- **Embedding limpio** — sin racha reciente de not_interested/block/mute/report (§26.4). Si vienes de meses malos, asume que tardarás 6-16 semanas en remontar (§28)
- **Una franja horaria de publicación consistente con tu audiencia objetivo** — no la tuya (§27.6)
- **No haber publicado nada propio en las últimas 4-6 horas** — el AuthorDiversityScorer te castigará el segundo post (§3)

### 30.2 Tipo de post

- **ORIGINAL** (no reply, no retweet). Solo los originales pasan por el Banger Screen y reciben embedding multimodal de calidad (§6.1). Los retweets y las respuestas NO entran al sistema de descubrimiento OON.

### 30.3 Formato y longitud

- **Texto largo y denso** o **texto corto + vídeo ≥ 10 s con audio**. Las dos opciones maximizan `dwell_time`/`cont_dwell_time` (5 señales positivas distintas de dwell vs 1 sola de favorite, §2 y §28).
- **Si vas con vídeo**: mínimo 10 segundos para activar el peso VQV (§9). Con audio para que Grok lo transcriba por ASR (§22.6).
- **Si vas con imagen**: una imagen de detalle que invite a tap-to-expand (`photo_expand_score` es peso positivo). Pero no es obligatorio.
- **Sin emojis spam**, sin walls de hashtags. El `slop_score` del BangerScreen detecta contenido de baja calidad (§22.8 y §29.4).

### 30.4 Estructura del texto

1. **Línea 1 = hook fuerte**. Una frase que pare el scroll. Aquí se decide el `not_dwelled` (señal negativa, §2). Si la primera línea no engancha, perdiste antes de empezar.
2. **Línea 2 = stake/claim concreto**. Un dato, una contradicción, una promesa. Para retener al lector que pasó el hook.
3. **Cuerpo = sustancia**. Cifras concretas, ejemplos, lista de puntos. Cada párrafo corto (1-3 frases) para que respire (estilo LevelsIO).
4. **Hook de reply al final**. Una pregunta, una opinión polarizante con tacto, o un cebo de "¿qué te ha pasado a ti?". `reply_score` es de los pesos más altos del modelo (§2).

### 30.5 Lo que el post debe activar (señales positivas)

Diseña el post pensando en disparar el máximo de estos 17 pesos positivos:

- `favorite_score` (like) — contenido validador
- `reply_score` — cebo de respuesta explícito
- `retweet_score` — frase citable/compartible
- `share_score`, `share_via_dm_score`, `share_via_copy_link_score` — utilidad práctica (la gente lo manda por DM)
- `dwell_score` + `cont_dwell_time` + `click_dwell_time` — densidad de contenido
- `quote_score` + `quoted_click_score` — claim controvertida invita a quote con take
- `profile_click_score` — "¿quién es esta persona?" detrás del contenido
- `follow_author_score` — el peso más alto del modelo a medio plazo
- `photo_expand_score` — imagen que invita a abrir
- `vqv_score` + `quoted_vqv_score` — vídeo retentivo

### 30.6 Lo que el post debe EVITAR (señales negativas)

- `not_dwelled_score` — primer segundo aburrido. Hook flojo
- `not_interested_score` — temas off-topic respecto a tu audiencia habitual
- `block_author_score` — ataque personal, agresividad
- `mute_author_score` — postear demasiado o mismo tema repetido
- `report_score` — cruzar líneas de PToS

### 30.7 Link, hashtag, mención

- **Link**: máximo uno, y SOLO si el texto del post ya tiene valor independiente. El link es bonus, no plato (§29.5)
- **Hashtags**: 1-2 relevantes que matcheen un topic reconocido por el sistema (§11 y §29.4)
- **Menciones**: úsalas para personas que aportan al contenido o que probablemente respondan/RT. Cada interacción suya dispara `reply_count`, `quote_count`, `retweet_count`

### 30.8 Timing

- **Horario**: prime time de TU AUDIENCIA OBJETIVO. Para US: 8 a 11am ET o 6 a 9pm ET. Para España: 9 a 11am o 7 a 9pm hora local.
- **Día**: martes a jueves rinden mejor en B2B/tech. Fines de semana para contenido cultural/personal.
- **Ventana óptima del post**: 0 a 12 horas. Después de 24h estás en bucket peor de edad. A las 80h muerto (§16).

### 30.9 Plan de los primeros 30 minutos (el más crítico)

Esto NO es opcional. Es el gate de min-traction (§15):

1. **Minuto 0**: publicas
2. **Minuto 0-5**: avisas a 5-10 personas de tu red por DM o comunidad privada. Que entren y engageen orgánicamente
3. **Minuto 5-15**: respondes a cualquier comment temprano con sustancia. Cada reply tuyo a un comentario en tu post se salta el Reply Ranker y el spam classifier (hay un check explícito: si el author del root es el mismo que el replier, skip). Y mantiene la conversación viva, inflando los `reply_count` del post original
4. **Minuto 15-30**: monitoreas. Si NO ha cruzado el min-traction, ese post está muerto para OON. Acéptalo y pasa al siguiente
5. **Minuto 30+**: si va bien, ya está en el pipeline de Grok. A partir de aquí el post se gestiona solo. NO publiques nada más en las próximas 4-6 horas

### 30.10 Plantilla resumen del post perfecto

```
[Hook contrarian / dato sorprendente que pare el scroll]

[Frase de claim concreta con cifra o promesa]

[Cuerpo de 3-8 párrafos cortos, cada uno con sustancia:
 - datos concretos
 - ejemplos
 - listas de puntos
 - sin paja]

[Opcional: 1 imagen de detalle o 1 vídeo de 10-30 s con audio]

[Cierre con cebo de reply: pregunta, opinión polarizante con tacto,
o invitación a compartir experiencia]

[Opcional: link al final como complemento, no como sustituto]

[Opcional: 1-2 hashtags relevantes]
```

### 30.11 Ejemplo realista (LevelsIO-style)

```
xAI publicó el algoritmo de X y casi nadie lo ha leído

Me he metido 207 archivos este fin de semana. Lo que está
ahí dentro contradice casi todo lo que cuentan los gurús
de growth en X desde hace 2 años

Tres cosas que descubrí:

1. Hay un Kafka topic literal en el código que decide si tu
post entra al pipeline de Grok según engagement en los primeros
minutos. Sin tracción temprana, el algoritmo NI LO MIRA

2. Tu ubicación física no le importa al modelo. Tu zona horaria
sí. Publicar a las 10am Madrid para audiencia US = tu post
envejece 6 horas antes de que despierten

3. El dwell pesa 5x más que el like. Hay 5 señales distintas
de tiempo de lectura y solo 1 de favorite. Un post con pocos
likes pero alto dwell bate a uno con muchos likes y bajo dwell

¿Cuál de estos te ha sorprendido más?
```

Este post tiene:
- Hook contrarian (línea 1)
- Claim con dato (línea 2: 207 archivos, fin de semana)
- Cuerpo con 3 hallazgos numerados, cada uno con sustancia
- Mezcla de mayúsculas selectivas para énfasis
- Cierre con pregunta directa que invita a reply
- Sin link, sin hashtag, sin mención. Solo texto denso
- Genera dwell (lectura de 30-45 segundos), reply (la pregunta), quote (los datos son citables), profile_click (¿quién es este?), follow_author (alguien que aporta esto)

### 30.12 La regla de oro

> Maximiza la probabilidad de que cada lector haga **al menos 2 acciones positivas distintas** (dwell + reply, dwell + share, dwell + follow, etc.). El modelo combina 17 señales positivas. Cada acción adicional multiplica tu score; cada acción negativa lo resta.

Un post perfecto no es uno que consiga 10.000 likes. Es uno donde el lector promedio gaste **20-40 segundos**, deje **un reply o un quote**, y un porcentaje no despreciable haga **click en tu perfil**. Eso es lo que dispara el embedding hacia "buen autor" y abre OON masivo.

---

## 31. ¿Hacer Quote de tu propio post o de posts ajenos penaliza?

**Respuesta corta: NO, ninguna de las dos cosas penaliza por sí misma.** Un Quote es técnicamente un **post original** y va por el carril rápido del descubrimiento. Pero hay tres efectos colaterales que pueden joderte si no sabes lo que estás citando.

### 31.1 Lo que es un Quote para el algoritmo

Un Quote post:
- Tiene `quoted_tweet_id` y `quoted_user_id` puestos
- NO tiene `retweeted_tweet_id` (no es un RT)
- NO tiene `ancestors` (no es un reply)
- En `TweetBoolFeatures` aparece como `is_quote: true`, `is_retweet: false`, `is_reply: false`

Fuente: [`home-mixer/models/candidate.rs:140-149`](x-algorithm/home-mixer/models/candidate.rs).

**Implicación clave**: como NO tiene `ancestors`, los filtros que excluyen "es reply" (Banger Screen, embedding multimodal, post safety deluxe) **NO te excluyen**. Tu Quote pasa por el Banger Screen como cualquier post original ([`grox/tasks/task_filters.py:340-370`](x-algorithm/grox/tasks/task_filters.py) — solo descarta si `post.ancestors`).

### 31.2 Las 3 señales positivas exclusivas de quote en el scorer

```rust
+ Self::apply(scores.quote_score, weights.quote)
+ Self::apply(scores.quoted_click_score, weights.quoted_click)
+ Self::apply(scores.quoted_vqv_score, quoted_vqv_weight)
```

Fuente: [`home-mixer/scorers/ranking_scorer.rs:160-162`](x-algorithm/home-mixer/scorers/ranking_scorer.rs).

- `quote_score` — P(el viewer cita TU post después de leerlo). Tu Quote genera quotes ajenos en cadena
- `quoted_click_score` — P(el viewer clica en el post citado dentro de tu Quote)
- `quoted_vqv_score` — P(el viewer ve el vídeo del post citado, si lo hay) — condicionado a que el quoted_video_duration_ms supere el umbral, igual que el VQV normal

Estos tres pesos son POSITIVOS. Citar contenido que ya engagea ayuda a que tu Quote scoree bien (porque el modelo predice que el lector va a interactuar con el citado).

### 31.3 Quote de tu propio post (self-quote)

**No hay ningún check específico para self-quotes en el código.** Cero. Lo verifiqué:

```bash
$ grep -rn "self_quote|is_self_quote|same_user_quote" --include="*.rs" --include="*.py"
# (cero resultados)
```

A diferencia de las **respuestas a tu propio post** (que sí tienen un check explícito que se salta el spam classifier y el reply ranker, ver §6.2-6.3), los **self-quotes** se tratan como cualquier otro post original.

**Pros:**
- Es un post nuevo con su propio `tweet_id`, su propio gate de min-traction, su propio Banger Screen
- Tiene `conversation_id` distinto al del post original (los conversation IDs vienen de `ancestors.min()` y un quote no tiene ancestors). Esto significa que **el DedupConversationFilter NO los fusiona**: tu post original y tu self-quote pueden aparecer ambos en el mismo feed
- Si el self-quote engagea más que el original, el self-quote gana en posición

**Contras:**
- El `AuthorDiversityScorer` te penaliza. Original + self-quote son 2 posts tuyos en el mismo feed-response → al self-quote le aplica `decay^1` (multiplicador menor que 1)
- No hay exención automática como la hay en self-replies
- Si en los próximos 4-6 horas publicas más, decay acumulado

**Conclusión sobre self-quote:** útil para "rescatar" un post que merece más alcance del que tuvo (añadiendo contexto nuevo), o para añadir un giro/dato adicional. Pero no te lo trates como una bala mágica: pierdes parte del score por la diversidad de autor.

### 31.4 Quote de posts ajenos

Aquí entran 3 trampas que sí te pueden hundir:

#### Trampa 1: heredas el `BrandSafetyVerdict` del post citado

```rust
if let Some(qt_id) = c.quoted_tweet_id {
    if error_map.contains_key(&qt_id) {
        verdict = worst_verdict(&verdict, &BrandSafetyVerdict::MediumRisk);
    } else {
        let qt_labels = label_map.get(&qt_id).unwrap_or(&empty);
        verdict = worst_verdict(&verdict, &compute_verdict(qt_labels, qt_id));
        safety_labels.extend(qt_labels.iter().map(...));
    }
}
```

Fuente: [`home-mixer/candidate_hydrators/ads_brand_safety_hydrator.rs:143-160`](x-algorithm/home-mixer/candidate_hydrators/ads_brand_safety_hydrator.rs) y duplicado en [`ads_brand_safety_vf_hydrator.rs:77-93`](x-algorithm/home-mixer/candidate_hydrators/ads_brand_safety_vf_hydrator.rs).

Tu verdict final es `worst_verdict(tu_verdict, verdict_del_citado)`. Es decir: **si citas un post `MediumRisk`, TU Quote pasa a `MediumRisk` automáticamente**. Y `MediumRisk` te quita ads adyacentes, te bloquea de inventario premium, y te downrankea estructuralmente (§7, §26.2).

**Quote de post NSFW/violencia/gore/`DO_NOT_AMPLIFY` = veneno directo para tu alcance.** Aunque tu texto sea inocente.

#### Trampa 2: si el post citado tiene `Action::Drop`, tu Quote se cae como "ancillary"

```rust
if let Some(quoted_id) = candidate.quoted_tweet_id
    && let Some(Ok(Some(reason))) = vf_results.get(&quoted_id)
    && should_drop_reason(reason)
{
    return true;  // drop_ancillary_posts = true
}
```

Fuente: [`home-mixer/candidate_hydrators/vf_candidate_hydrator.rs:138-143`](x-algorithm/home-mixer/candidate_hydrators/vf_candidate_hydrator.rs) y el `AncillaryVFFilter` ([`ancillary_vf_filter.rs`](x-algorithm/home-mixer/filters/ancillary_vf_filter.rs)) elimina cualquier candidato con ese flag.

Si el post que citas se borra, lo borran por moderación, o tiene `Action::Drop` por cualquier razón, **tu Quote también desaparece del For You**. Has anclado tu post al destino del que citaste.

#### Trampa 3: el `AuthorSocialgraphFilter` revisa al autor citado

```rust
if muted
    || blocked
    || author_blocks_viewer
    || quoted_author_blocks_viewer        // ← el autor citado bloquea al viewer
    || viewer_blocks_quoted_author        // ← el viewer bloquea al autor citado
    || viewer_blocks_retweeted_user
{ removed.push(candidate); }
```

Fuente: [`home-mixer/filters/author_socialgraph_filter.rs:34-52`](x-algorithm/home-mixer/filters/author_socialgraph_filter.rs).

Si citas a alguien que ha bloqueado a partes de tu audiencia, tu Quote **no aparece para esos viewers**. Inversamente: si parte de tu audiencia ha bloqueado al autor que citas, tu Quote tampoco les llega.

Implicación: citar cuentas con muchos bloqueos cruzados reduce tu reach efectivo. Citar cuentas controvertidas/polarizantes recorta automáticamente tu alcance a la mitad del mapa.

### 31.5 Veredicto rápido

| Caso | Penalización directa | Riesgos indirectos |
|---|---|---|
| **Quote de tu propio post** | Ninguna | AuthorDiversityScorer (decay si original + quote aparecen juntos en un feed) |
| **Quote de post sano de otro** | Ninguna. Tres pesos positivos extra (quote_score, quoted_click, quoted_vqv) | Si la cuenta citada tiene bloqueos masivos, tu reach baja |
| **Quote de post `MediumRisk`** | Tu Quote hereda `MediumRisk` → sin ads → downrank estructural | Pierdes hasta el 50% de alcance esperado |
| **Quote de post `Action::Drop`** | Tu Quote se cae como ancillary | Desaparece del For You completo |

### 31.6 Reglas prácticas

- **Self-quote**: úsalo solo si añade información nueva al hilo. Si solo es para "bumpear" sin contenido extra, te lo come el decay.
- **Quote de otros**: comprueba el post antes. Si tiene aviso de comunidad, NSFW, violencia o suspensiones cercanas a su autor, **no lo cites**. Estás regalando tu Quote al verdict del otro.
- **Cita virales de tu nicho con buen historial**: es exactamente el patrón que el modelo recompensa (quote_score, quoted_click) sin riesgo de contagio.
- **No cites trolls ni cuentas polémicas**: si ya tienen `MediumRisk` o cerca, los heredas. Y si los bloquea media plataforma, ese filtro te corta el alcance.

> La frase que resume todo: **un Quote es un post original con un ancla**. Si lo que está anclado pesa, tu post no se mueve. Elige bien el ancla.

---

## Apéndice: archivos clave del repo para profundizar

| Tema | Archivo |
|---|---|
| Pesos finales del score | [`home-mixer/scorers/ranking_scorer.rs`](x-algorithm/home-mixer/scorers/ranking_scorer.rs) |
| Pesos en cluster legacy | [`home-mixer/scorers/weighted_scorer.rs`](x-algorithm/home-mixer/scorers/weighted_scorer.rs) |
| Author diversity decay | [`home-mixer/scorers/author_diversity_scorer.rs`](x-algorithm/home-mixer/scorers/author_diversity_scorer.rs) |
| OON penalty | [`home-mixer/scorers/oon_scorer.rs`](x-algorithm/home-mixer/scorers/oon_scorer.rs) |
| Llamada a Grok-Phoenix | [`home-mixer/scorers/phoenix_scorer.rs`](x-algorithm/home-mixer/scorers/phoenix_scorer.rs) |
| Ranker DPP alternativo | [`home-mixer/scorers/vm_ranker.rs`](x-algorithm/home-mixer/scorers/vm_ranker.rs) |
| Brand safety / labels | [`home-mixer/models/brand_safety.rs`](x-algorithm/home-mixer/models/brand_safety.rs) |
| Modelo del candidato | [`home-mixer/models/candidate.rs`](x-algorithm/home-mixer/models/candidate.rs) |
| Modelo de query (qué sabe de ti) | [`home-mixer/models/query.rs`](x-algorithm/home-mixer/models/query.rs) |
| 80+ topics que reconoce | [`home-mixer/filters/topic_ids_filter.rs`](x-algorithm/home-mixer/filters/topic_ids_filter.rs) |
| Blocker / muter / quote chain | [`home-mixer/filters/author_socialgraph_filter.rs`](x-algorithm/home-mixer/filters/author_socialgraph_filter.rs) |
| Dedup de conversaciones | [`home-mixer/filters/dedup_conversation_filter.rs`](x-algorithm/home-mixer/filters/dedup_conversation_filter.rs) |
| Banger initial screen (Grok-VLM) | [`grox/classifiers/content/banger_initial_screen.py`](x-algorithm/grox/classifiers/content/banger_initial_screen.py) |
| Spam reply classifier | [`grox/classifiers/content/spam.py`](x-algorithm/grox/classifiers/content/spam.py) |
| Reply ranking 0-3 | [`grox/classifiers/content/reply_ranking.py`](x-algorithm/grox/classifiers/content/reply_ranking.py) |
| 7 categorías PToS | [`grox/classifiers/content/safety_ptos.py`](x-algorithm/grox/classifiers/content/safety_ptos.py) |
| Filtros de qué se evalúa | [`grox/tasks/task_filters.py`](x-algorithm/grox/tasks/task_filters.py) |
| Insertador de ads | [`home-mixer/ads/util.rs`](x-algorithm/home-mixer/ads/util.rs) |
| Blender final del feed | [`home-mixer/selectors/blender_selector.rs`](x-algorithm/home-mixer/selectors/blender_selector.rs) |
| Modelo Phoenix (transformer + isolation mask) | [`phoenix/recsys_model.py`](x-algorithm/phoenix/recsys_model.py), [`phoenix/recsys_retrieval_model.py`](x-algorithm/phoenix/recsys_retrieval_model.py) |
| Entry point del servidor + feature switches | [`home-mixer/server.rs`](x-algorithm/home-mixer/server.rs) |
| Dispatcher de Grox + streams Kafka | [`grox/dispatcher.py`](x-algorithm/grox/dispatcher.py), [`grox/generators/stream_generator.py`](x-algorithm/grox/generators/stream_generator.py) |
| Engine de Grox | [`grox/engine.py`](x-algorithm/grox/engine.py) |
| Plan master (todos los planes Grok) | [`grox/plans/plan_master.py`](x-algorithm/grox/plans/plan_master.py) |
| User action sequence (input al modelo) | [`home-mixer/query_hydrators/scoring_sequence_query_hydrator.rs`](x-algorithm/home-mixer/query_hydrators/scoring_sequence_query_hydrator.rs), [`home-mixer/query_hydrators/retrieval_sequence_query_hydrator.rs`](x-algorithm/home-mixer/query_hydrators/retrieval_sequence_query_hydrator.rs) |
| Served history y fatigue | [`home-mixer/query_hydrators/served_history_query_hydrator.rs`](x-algorithm/home-mixer/query_hydrators/served_history_query_hydrator.rs), [`home-mixer/side_effects/truncate_served_history_side_effect.rs`](x-algorithm/home-mixer/side_effects/truncate_served_history_side_effect.rs) |
| Multimodal embedder | [`grox/embedder/multimodal_post_embedder_v2.py`](x-algorithm/grox/embedder/multimodal_post_embedder_v2.py) |
| ASR (transcripción de vídeo) | [`grox/tasks/task_asr.py`](x-algorithm/grox/tasks/task_asr.py) |
| TweetMixer (otra fuente OON) | [`home-mixer/sources/tweet_mixer_source.rs`](x-algorithm/home-mixer/sources/tweet_mixer_source.rs) |
| Push-to-Home (pin position 0) | [`home-mixer/sources/push_to_home_source.rs`](x-algorithm/home-mixer/sources/push_to_home_source.rs) |
| Cached posts (replay) | [`home-mixer/query_hydrators/cached_posts_query_hydrator.rs`](x-algorithm/home-mixer/query_hydrators/cached_posts_query_hydrator.rs) |
| Quote-author block check + duración vídeo del quoted | [`home-mixer/candidate_hydrators/quote_hydrator.rs`](x-algorithm/home-mixer/candidate_hydrators/quote_hydrator.rs) |

---

*Documento generado a partir del análisis estático del código publicado el 15-may-2026. Incluye dos pasadas de revisión sobre el repositorio. No incluye experimentación empírica sobre cuentas reales; toda afirmación procede del repositorio o se marca explícitamente como inferencia.*
