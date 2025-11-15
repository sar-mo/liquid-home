"""
Scene Change Action Detector using llama.cpp
Analyzes two scene descriptions and determines appropriate smart home actions
Uses local inference with GGUF models
"""

import json
from enum import Enum
from dataclasses import dataclass
from typing import Optional
from llama_cpp import Llama

class Action(Enum):
    """Predefined smart home actions"""
    TURN_ON_LIGHT = "TURN_ON_LIGHT"
    TURN_OFF_LIGHT = "TURN_OFF_LIGHT"
    PLAY_MUSIC = "PLAY_MUSIC"
    STOP_MUSIC = "STOP_MUSIC"
    RAISE_THERMOSTAT = "RAISE_THERMOSTAT"
    LOWER_THERMOSTAT = "LOWER_THERMOSTAT"
    LOCK_DOOR = "LOCK_DOOR"
    UNLOCK_DOOR = "UNLOCK_DOOR"
    OPEN_BLINDS = "OPEN_BLINDS"
    CLOSE_BLINDS = "CLOSE_BLINDS"
    NO_ACTION = "NO_ACTION"


@dataclass
class SceneAnalysis:
    """Result of scene change analysis"""
    action: Action
    confidence: float
    reasoning: str
    scene_change: str


class SceneActionDetector:
    """Detects scene changes and maps them to smart home actions using llama.cpp"""
    
    def __init__(self, 
                 model_path: str,
                 n_ctx: int = 4096,
                 n_gpu_layers: int = -1,
                 verbose: bool = False):
        """
        Initialize the detector with llama.cpp
        
        Args:
            model_path: Path to GGUF model file
            n_ctx: Context window size
            n_gpu_layers: Number of layers to offload to GPU (-1 for all)
            verbose: Enable verbose logging
        """
        print(f"Loading model from: {model_path}")
        print(f"GPU layers: {n_gpu_layers}, Context: {n_ctx}")
        
        self.llm = Llama(
            model_path=model_path,
            n_ctx=n_ctx,
            n_gpu_layers=n_gpu_layers,
            verbose=verbose,
            n_threads=4,  # Adjust based on your CPU
            n_batch=512,  # Batch size for prompt processing
            use_mlock=True,  # Keep model in RAM
            use_mmap=True  # Use memory mapping
        )
        
        print("✓ Model loaded successfully\n")
        
    def analyze_scene_change(self, 
                            scene_before: str, 
                            scene_after: str,
                            temperature: float = 0.1,
                            max_tokens: int = 256) -> SceneAnalysis:
        """
        Analyze scene change and determine appropriate action
        
        Args:
            scene_before: Description of the scene before
            scene_after: Description of the scene after
            temperature: Sampling temperature (lower = more deterministic)
            max_tokens: Maximum tokens to generate
            
        Returns:
            SceneAnalysis with action, confidence, and reasoning
        """
        
        # Create prompt
        prompt = self._create_prompt(scene_before, scene_after)
        
        # Check prompt length
        tokens = self.llm.tokenize(prompt.encode('utf-8'))
        prompt_tokens = len(tokens)
        
        if prompt_tokens + max_tokens > self.llm.n_ctx():
            print(f"⚠️  Warning: Prompt too long ({prompt_tokens} tokens). Truncating...")
            # Use shorter prompt
            prompt = self._create_short_prompt(scene_before, scene_after)
            tokens = self.llm.tokenize(prompt.encode('utf-8'))
            prompt_tokens = len(tokens)
        
        print(f"Prompt tokens: {prompt_tokens}, Max generation: {max_tokens}")
        
        try:
            # Reset context before generation
            self.llm.reset()
            
            # Generate response
            response = self.llm(
                prompt,
                max_tokens=max_tokens,
                temperature=temperature,
                top_p=0.95,
                top_k=40,
                repeat_penalty=1.1,
                stop=["</s>", "\n\nUSER:", "\n\nASSISTANT:", "<|im_end|>"],
                echo=False
            )
            
            # Extract generated text
            result_text = response['choices'][0]['text'].strip()
            
            # Parse response
            return self._parse_response(result_text)
            
        except Exception as e:
            print(f"Error during inference: {e}")
            import traceback
            traceback.print_exc()
            return SceneAnalysis(
                action=Action.NO_ACTION,
                confidence=0.0,
                reasoning=f"Error: {str(e)}",
                scene_change="Unable to analyze"
            )
    
    def _create_prompt(self, scene_before: str, scene_after: str) -> str:
        """Create the prompt for the model"""
        
        actions_list = ", ".join([a.value for a in Action])
        
        prompt = f"""<|im_start|>system
You are a smart home assistant. Analyze scene changes and output JSON only.

Actions: {actions_list}

Rules:
- Person entering + dark → TURN_ON_LIGHT
- Person leaving → TURN_OFF_LIGHT, LOWER_THERMOSTAT, LOCK_DOOR
- Multiple people → PLAY_MUSIC
- No change → NO_ACTION

Output format:
{{"action": "ACTION_NAME", "confidence": 0.95, "scene_change": "what changed", "reasoning": "why"}}<|im_end|>
<|im_start|>user
Before: {scene_before}
After: {scene_after}

JSON:<|im_end|>
<|im_start|>assistant
"""
        
        return prompt
    
    def _create_short_prompt(self, scene_before: str, scene_after: str) -> str:
        """Create a shorter prompt if context is running out"""
        
        prompt = f"""Scene before: {scene_before}
Scene after: {scene_after}

Task: Determine smart home action. Output JSON: {{"action": "ACTION_NAME", "confidence": 0.9, "scene_change": "brief", "reasoning": "brief"}}

JSON:
"""
        return prompt
    
    def _parse_response(self, response_text: str) -> SceneAnalysis:
        """Parse LLM response into SceneAnalysis"""
        try:
            # Clean up response
            response_text = response_text.strip()
            
            # Handle code blocks
            if "```json" in response_text:
                response_text = response_text.split("```json")[1].split("```")[0].strip()
            elif "```" in response_text:
                response_text = response_text.split("```")[1].split("```")[0].strip()
            
            # Extract JSON if embedded in text
            if "{" in response_text and "}" in response_text:
                start = response_text.find("{")
                end = response_text.rfind("}") + 1
                response_text = response_text[start:end]
            
            data = json.loads(response_text)
            
            # Parse action
            action_str = data.get("action", "NO_ACTION")
            try:
                action = Action[action_str]
            except KeyError:
                # Try to find closest match
                action = Action.NO_ACTION
                for a in Action:
                    if a.value in action_str.upper():
                        action = a
                        break
            
            return SceneAnalysis(
                action=action,
                confidence=float(data.get("confidence", 0.5)),
                reasoning=data.get("reasoning", ""),
                scene_change=data.get("scene_change", "")
            )
            
        except (json.JSONDecodeError, ValueError) as e:
            # Fallback: try to extract action from text
            print(f"JSON parse error: {e}")
            print(f"Raw response: {response_text[:200]}")
            
            action = Action.NO_ACTION
            for a in Action:
                if a.value in response_text.upper():
                    action = a
                    break
            
            return SceneAnalysis(
                action=action,
                confidence=0.3,
                reasoning="Extracted from unstructured response",
                scene_change=response_text[:100]
            )


def main():
    """Example usage"""
    
    # Example scenarios
    examples = [
        {
            "name": "Person entering at night",
            "before": "Empty living room, dark, nighttime, lights are off",
            "after": "Person standing at the entrance, dark room, nighttime"
        },
        {
            "name": "Person leaving house",
            "before": "Person in living room, daytime, lights on, comfortable temperature",
            "after": "Empty living room, daytime, door just closed"
        },
        {
            "name": "Morning routine",
            "before": "Person sleeping, bedroom, early morning, blinds closed, dark",
            "after": "Person awake and standing, bedroom, morning light visible outside"
        },
        {
            "name": "Party starting",
            "before": "Two people in living room, talking",
            "after": "Five people in living room, standing in groups, social gathering"
        },
        {
            "name": "No significant change",
            "before": "Person reading book on couch, afternoon",
            "after": "Person still reading book on couch, afternoon"
        }
    ]
    
    print("Scene Change Action Detector - llama.cpp Edition\n")
    print("=" * 70)
    
    
    model_path = "models/LFM2-1.2B-Q4_K_M.gguf"
    
    print(f"Model path: {model_path}")
    print("If model not found, download from https://huggingface.co/")
    print("Example: huggingface.co/bartowski/Llama-3.2-3B-Instruct-GGUF\n")
    
    try:
        # Initialize detector
        detector = SceneActionDetector(
            model_path=model_path,
            n_ctx=4096,
            n_gpu_layers=-1  # Use -1 for full GPU, 0 for CPU only
        )
    except Exception as e:
        print(f"\n❌ Error loading model: {e}")
        print("\nMake sure to:")
        print("1. Download a GGUF model file")
        print("2. Update model_path in the code")
        print("3. Install: pip install llama-cpp-python")
        return
    
    # Process examples
    for i, example in enumerate(examples, 1):
        print(f"\n📹 Scenario {i}: {example['name']}")
        print("-" * 70)
        print(f"Before: {example['before']}")
        print(f"After:  {example['after']}")
        
        # Analyze
        result = detector.analyze_scene_change(
            scene_before=example['before'],
            scene_after=example['after']
        )
        
        # Display results
        print(f"\n🎯 Action: {result.action.value}")
        print(f"📊 Confidence: {result.confidence:.2%}")
        print(f"🔄 Change: {result.scene_change}")
        print(f"💭 Reasoning: {result.reasoning}")
        print("=" * 70)


if __name__ == "__main__":
    main()