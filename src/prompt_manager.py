# src/prompt_manager.py
import os
import yaml
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

class PromptManager:
    def __init__(self, prompts_dir="prompts"):
        self.prompts_dir = Path(prompts_dir).resolve()
        if not self.prompts_dir.is_dir():
            raise FileNotFoundError(f"Prompts directory not found: {self.prompts_dir}")
        self.loaded_prompts = {} # Cache: { set_name: merged_prompts_dict }

    def _load_yaml(self, file_path):
        """Loads a single YAML file safely."""
        if not file_path.is_file():
            return None
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                return yaml.safe_load(f)
        except yaml.YAMLError as e:
            logger.error(f"Error parsing YAML file {file_path}: {e}")
            return None
        except Exception as e:
            logger.error(f"Error reading file {file_path}: {e}")
            return None

    def _load_prompt_set(self, set_name="default"):
        """Loads a specific prompt set, merging with default if necessary."""
        if set_name in self.loaded_prompts:
            return self.loaded_prompts[set_name]

        logger.debug(f"Loading prompt set: '{set_name}'")
        specific_path = self.prompts_dir / f"{set_name}.yaml"
        default_path = self.prompts_dir / "default.yaml"

        specific_prompts = self._load_yaml(specific_path)
        default_prompts = self._load_yaml(default_path)

        merged_prompts = {}

        # Merge logic: Specific overrides default
        if default_prompts:
            merged_prompts.update(default_prompts) # Start with defaults

        if specific_prompts:
            # Deep merge might be needed if prompts are heavily nested
            # For simple structure, dict.update works but overrides entire keys
            # Using ChainMap provides a view that prioritizes specific_prompts
            # For saving, we might need a true deep merge later if structure gets complex
            merged_prompts.update(specific_prompts) # Specific prompts override default keys
            logger.debug(f"Loaded and merged '{set_name}.yaml' with 'default.yaml'.")
        elif default_prompts:
            logger.debug(f"Loaded only 'default.yaml' (specific set '{set_name}' not found).")
        else:
            logger.error(f"Failed to load prompts for set '{set_name}' and 'default.yaml' not found.")
            self.loaded_prompts[set_name] = None # Cache failure
            return None

        self.loaded_prompts[set_name] = merged_prompts
        return merged_prompts

    def get_prompt(self, prompt_key, set_name="default"):
        """Gets the raw prompt template string for a given key and set."""
        prompt_data = self._load_prompt_set(set_name)
        if not prompt_data:
            logger.error(f"Prompt set '{set_name}' not loaded or empty.")
            return None

        # Handle nested keys like "script_generation.initial_script_article"
        keys = prompt_key.split('.')
        current_level = prompt_data
        try:
            for key in keys:
                current_level = current_level[key] # Use direct access after load
            if isinstance(current_level, str):
                return current_level
            else:
                logger.error(f"Prompt key '{prompt_key}' in set '{set_name}' did not resolve to a string value.")
                return None
        except KeyError:
            logger.error(f"Prompt key '{prompt_key}' not found in prompt set '{set_name}' (or default).")
            return None
        except TypeError: # Handle cases where intermediate key isn't a dict
             logger.error(f"Invalid prompt key structure '{prompt_key}' for set '{set_name}'.")
             return None


    def format_prompt(self, prompt_key, context, set_name="default"):
        """Gets the prompt template and formats it with the given context."""
        template = self.get_prompt(prompt_key, set_name)
        if template is None:
            # Error already logged by get_prompt
            return None

        try:
            # Use str.format for placeholder replacement
            formatted = template.format(**context)
            return formatted
        except KeyError as e:
            logger.error(f"Missing key '{e}' in context dictionary when formatting prompt '{prompt_key}' for set '{set_name}'.")
            logger.debug(f"Template: {template[:200]}...") # Log beginning of template
            logger.debug(f"Provided context keys: {list(context.keys())}")
            return None
        except Exception as e:
            logger.error(f"Error formatting prompt '{prompt_key}' for set '{set_name}': {e}", exc_info=True)
            return None