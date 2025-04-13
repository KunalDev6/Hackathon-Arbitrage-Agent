import os
import logging
import sys
import json # Added for JSON output
from dotenv import load_dotenv

# Ensure Portia library is installed
try:
    # Import only necessary components based on documentation
    from portia import (
        Config,
        LLMModel,
        LLMProvider,
        Portia
    )
    from portia.config import LogLevel # Import LogLevel enum
except ImportError as e: # Capture the actual exception
    # Update the error message to show the real error
    print(f"ERROR: Failed to import Portia library. Details: {e}")
    print("Ensure 'portia-sdk-python[google]' is correctly installed in your environment.")
    sys.exit(1) # Exit if Portia is not installed

# Import Portia's open source tools, including the search tool
from portia import PlanRunState # Import state enum earlier
try:
    from portia.open_source_tools.registry import open_source_tool_registry
except ImportError as e:
    print(f"ERROR: Failed to import Portia's open source tools. Details: {e}")
    sys.exit(1)

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger("TokenFinderAgent")

def run_agent():
    """Initializes and runs the Portia Agent to find promising Solana tokens."""
    # Load environment variables (for GOOGLE_API_KEY, TAVILY_API_KEY, etc.)
    load_dotenv()
    logger.info("Loaded environment variables from .env file (if found).")
    GOOGLE_API_KEY = os.getenv('GOOGLE_API_KEY')
    TAVILY_API_KEY = os.getenv('TAVILY_API_KEY') # Needed for Search Tool
    PORTIA_API_KEY = os.getenv('PORTIA_API_KEY') # Potentially needed by Portia

    if not GOOGLE_API_KEY:
        logger.error("GOOGLE_API_KEY not found in environment variables. Please set it in the .env file.")
        print("FATAL: GOOGLE_API_KEY is required.")
        return
    if not TAVILY_API_KEY:
        logger.warning("TAVILY_API_KEY not found in environment variables. Search Tool may not function.")
        # Optionally exit if Tavily is strictly required
        # print("FATAL: TAVILY_API_KEY is required for the Search Tool.")
        # return
    if not PORTIA_API_KEY:
         logger.warning("PORTIA_API_KEY not found. Cloud features (logging/storage) may not function.")

    # --- Configure Portia using the user's example --- 
    logger.info(f"Configuring Portia with Google GenAI Provider and {LLMModel.GEMINI_1_5_FLASH.value} model...")
    try:
        # Using default_config and overriding essentials for clarity
        # Set log level to DEBUG to see more details if needed
        portia_config = Config.from_default(
            llm_provider=LLMProvider.GOOGLE_GENERATIVE_AI,
            llm_model_name=LLMModel.GEMINI_1_5_FLASH, # Use 1.5 Flash as per your example context
            google_api_key=GOOGLE_API_KEY,
            portia_api_key=PORTIA_API_KEY, # Pass Portia key if available
            default_log_level=LogLevel.INFO # Use Portia's LogLevel enum
        )
        logger.info("Portia configuration created.")
    except Exception as e:
        logger.error(f"Failed to create Portia config: {e}", exc_info=True)
        print(f"FATAL: Failed to create Portia configuration: {e}")
        return
    # --------------------------------------------------

    logger.info("Initializing Portia with Open Source Tools...")
    try:
        # Initialize Portia with the config and the open source tool registry
        app = Portia(config=portia_config, tools=open_source_tool_registry)
        logger.info("Portia initialized successfully with Open Source Tools.")
    except Exception as e:
        logger.error(f"An unexpected error occurred during Portia initialization: {e}", exc_info=True)
        print(f"FATAL: Unexpected error during Portia setup: {e}")
        return

    # Define a query asking for more tokens and broadening scope slightly
    solana_token_query = """
Find names or symbols of potentially interesting newly launched (within past 60 days) OR trending Solana tokens. Search for related official announcements, developer activity, or influencer mentions for these tokens. 

**IMPORTANT: List ONLY the identified token symbols or names (up to 10 if possible), separated by commas.** Do not include descriptions, links, or any other text.
"""

    print("\n--- Running Broader Solana Token Discovery Query ---")
    print(f"\nQuery: {solana_token_query}")

    identified_tokens = []
    try:
        # Use app.run() to generate plan and execute it directly
        plan_run = app.run(solana_token_query)

        print(f"\n--- Execution Result (PlanRun ID: {plan_run.id}) ---")

        # Check for Execution Errors First
        # Note: Based on previous errors, plan_run might not have .error
        # We'll check the state instead. PlanRunState needs to be imported.
        # Let's import it and refine this logic.
        # For now, assume success if no exception was raised by app.run()

        print(f"Status: {plan_run.state.value}")

        if plan_run.state == PlanRunState.COMPLETE:
            if plan_run.outputs and plan_run.outputs.final_output:
                final_output_obj = plan_run.outputs.final_output
                print("\nRaw Final Output:")
                print(final_output_obj)

                # Attempt to extract token names/symbols (simple parsing)
                final_output_text = ""
                if hasattr(final_output_obj, 'value') and final_output_obj.value:
                    final_output_text = str(final_output_obj.value)
                elif isinstance(final_output_obj, dict) and 'value' in final_output_obj:
                     final_output_text = str(final_output_obj['value'])
                else:
                    final_output_text = str(final_output_obj) # Fallback

                # Basic parsing - assumes LLM lists symbols/names
                # This will need refinement based on actual LLM output format
                potential_tokens = [word.strip('.,():[]{}') for word in final_output_text.split() if word.isupper() and len(word) > 2 and len(word) < 7]
                identified_tokens = list(set(potential_tokens)) # Get unique symbols
                print(f"\nPotentially identified tokens (simple parse): {identified_tokens}")

            else:
                print("\nPlan completed, but no specific final output was captured.")
        else:
             # Handle non-COMPLETE states (like FAILED)
             print(f"\nPlan finished with state: {plan_run.state.value}. Check logs or Portia dashboard.")
             # Attempt to access error attribute if it exists (might be added in future SDK versions)
             error_info = getattr(plan_run, 'error', 'No error attribute found')
             print(f"Further info (if available): {error_info}")


    except Exception as e:
        logger.error(f"Error running query: {e}", exc_info=True)
        print(f"Error processing query: {e}")

    # Save identified tokens to JSON file (Corrected Path)
    output_file = "identified_tokens.json" # Corrected path
    try:
        with open(output_file, 'w') as f:
            json.dump({"identified_tokens": identified_tokens}, f, indent=2)
        logger.info(f"Saved {len(identified_tokens)} identified tokens to {output_file}")
        print(f"\nSaved potentially identified tokens to {output_file}")
    except Exception as e:
        logger.error(f"Failed to save tokens to {output_file}: {e}")
        print(f"\nError saving tokens to {output_file}: {e}")

    print("\n--- Script Finished ---")

if __name__ == "__main__":
    run_agent() 