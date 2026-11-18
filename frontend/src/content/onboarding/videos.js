
export const MEDIA_HOST = 'https://giljo.ai'

const mediaAddress = (id, version, extension) =>
  [MEDIA_HOST, 'media', 'onboarding', `${id}.v${version}.${extension}`].join('/')

export const ONBOARDING_LESSONS = Object.freeze([
  Object.freeze({
    id: 'lesson01',
    title: 'Start with your product',
    version: 4,
    seconds: 47.866667,
    sha256: '780e1524b25719b600e742d643b67ef3765625b5f3ae8de61b2bf00e01ea642c',
    video: mediaAddress('lesson01', 4, 'mp4'),
    captions: mediaAddress('lesson01', 4, 'vtt'),
    transcript:
      "Your product defines what you're building and where you're going.\n\nProjects break that journey into small milestones.\n\nIn your coding tool, an orchestrator plans the work and coordinates the agents.\n\nGiljo HQ keeps the context, so each project builds on what came before.\n\nStart by telling Giljo HQ what you're building.\n\nAlready have code? Open your connected coding agent in that repository and give it our setup prompt.\n\nStarting with an idea? Use the interview prompt, then bring back the vision document it creates.\n\nAlready have a document? Upload it, then give the discovery prompt to your connected agent.\n\nYou can also fill in the product yourself.\n\nChoose your starting point, then review your product details.\n",
  }),
  Object.freeze({
    id: 'lesson02',
    title: 'Choose your first project',
    version: 2,
    seconds: 40.75,
    sha256: '1247859090e35fb2146105b18f99248553051ed8cd64aa8fa7d1d3c54e7b0145',
    video: mediaAddress('lesson02', 2, 'mp4'),
    captions: mediaAddress('lesson02', 2, 'vtt'),
    transcript:
      "Your product holds the bigger picture. A project describes one piece of work that moves it forward.\n\nFor a new hiking app, that could be setting up the first working screen. For an existing app, it might be trail search, a bug fix, or a security update.\n\nStart by talking to your connected coding agent. Tell it which product you're working on and what you'd like to achieve.\n\nAsk it to read the product context, help choose a small milestone, and create a project in Giljo HQ.\n\nThen review the objective together. You can refine it before preparing the work.\n\nCopy the starter prompt below to create your first project.\n",
  }),
  Object.freeze({
    id: 'lesson03',
    title: 'Prepare the work',
    version: 5,
    seconds: 47.07,
    sha256: 'f1496a55fede92eca0f4d81eed879b57fd406b3dfa786608e19d71ad0d8d9235',
    video: mediaAddress('lesson03', 5, 'mp4'),
    captions: mediaAddress('lesson03', 5, 'vtt'),
    transcript:
      "With your project defined, prepare the work. In Giljo HQ, this is called staging.\n\nFirst, choose how your agents will work.\n\nSub-agent mode keeps the work coordinated inside one coding tool's session, using its sub-agents.\n\nMulti-terminal mode uses separate terminals and can bring together different coding tools. The Message Hub lets the agents coordinate across them.\n\nChoose your mode, then select Stage. Paste the copied prompt into your coding tool.\n\nYour orchestrator reads the product context and relevant history, prepares the mission, selects agent roles, and writes their work orders.\n\nWhen staging is complete, it pauses for you.\n\nReview the plan. Ask for any changes before you approve implementation.\n",
  }),
  Object.freeze({
    id: 'lesson04',
    title: 'Build review and continue',
    version: 7,
    seconds: 56.7,
    sha256: '385490ae3a31f6119b2e168469f2178368d5020ad8bb45408728a24df460a74d',
    video: mediaAddress('lesson04', 7, 'mp4'),
    captions: mediaAddress('lesson04', 7, 'vtt'),
    transcript:
      "When the plan looks right, you're ready to begin.\n\nSelect Implement, then paste the implementation prompt into your orchestrator's coding session.\n\nYour orchestrator coordinates the agents as they carry out the work. Follow progress on the Jobs board, and use the Message Hub to follow their conversation and add your input.\n\nWhen the project closes, the agents record what changed, what was checked, and the decisions they made.\n\nThat record becomes 360 Memory.\n\nYour next project can draw on relevant memories alongside the product context and current code.\n\nReview the result. Then choose the next piece of work.\n\nEach project takes your product another step forward.\n\nReady to get going? Define your product, then ask your coding agent to help plan your first project.\n\nYou can revisit these tutorials from Tools, then Startup.\n\nMore advanced walkthroughs will be coming soon!\n",
  }),
])

export const ONBOARDING_SETUP_HELPER = Object.freeze({
  id: 'setup',
  title: 'Get your coding tool ready',
  version: 1,
  seconds: 42.2,
  sha256: '10804cd090f533a46aabc17c45a765b5449373d6641fcf5c6ca64ea5b7ac3427',
  video: mediaAddress('setup', 1, 'mp4'),
  captions: mediaAddress('setup', 1, 'vtt'),
  transcript:
    "Your coding tool is connected to Giljo HQ. Let's get it ready to work.\n\nIn your coding tool, say: Please run giljo_setup from the Giljo HQ MCP server and follow its setup instructions.\n\nThis guides your agent through installing the Giljo skill. The skill loads the latest instructions for working with your products, projects, tasks, and development workflow.\n\nSetup can also add a short introduction to your tool's startup instructions, such as AGENTS.md or CLAUDE.md, so future sessions start prepared.\n\nAlready completed setup? You're ready.\n\nLet's define your product and plan your first project.\n",
})

export const ONBOARDING_INTRO_VIDEO = Object.freeze({
  id: 'how-to-get-going',
  title: 'How to get going',
  version: 1,
  seconds: 108.233,
  sha256: '8758aaca95c422ebc4ba7911c6bd87a5d5097a7a7de9111d18b73ea2ab2ddc57',
  captionsSha256: 'b404ad46ec375ad3faa4844bf87d87d1bbd141ac0d3853dad8cccd0709816217',
  video: mediaAddress('how-to-get-going', 1, 'mp4'),
  captions: mediaAddress('how-to-get-going', 1, 'vtt'),
  transcript:
    "Let's get connected. You bring your AI. We provide Giljo HQ, the MCP server that gives your coding tool a place for context, plans, and work records. Your chosen tool and model do the thinking.\n\nGetting connected starts with adding Giljo HQ as an MCP server in the tool you already use.\n\nWhen you first sign in, the setup wizard walks you through it. There are ready-made connection instructions for Claude Code, Codex, and OpenCode, plus a generic option for other tools that support MCP.\n\nYou can choose browser sign-in through OAuth or connect with an API key. The wizard shows the options for your tool.\n\nCopy the command we provide, or give your coding agent the instruction link and ask it to help you connect. It can guide you through the setup and any sign-in you need to complete.\n\nYour tool may need a restart to pick up the connection. When Giljo HQ detects it connecting, the indicator turns green.\n\nNow ask your agent, “Can you see Giljo HQ?” Then ask it to run giljo_setup and follow the instructions it receives.\n\nThat adds the Giljo skill and startup guidance, helping your agent understand how to work with Giljo HQ. Follow any final restart instructions it gives you.\n\nNext, let's add your first product. The product is what you're building. Projects describe the work, agent types define the roles, and jobs give each agent its instructions.\n\nGiljo HQ provides three ready-made prompts to help you set up that product.\n\nAlready have code? Start there. Have a proposal? Bring that. Still exploring an idea? Begin with that.\n\nChoose the prompt that fits, and give it to your connected agent.\n\nYou're connected. Now let's give your ideas a place to begin.\n\nFor more Giljo HQ videos, visit giljo.ai.\n",
})
