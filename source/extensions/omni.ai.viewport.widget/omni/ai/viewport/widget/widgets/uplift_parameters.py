# SPDX-FileCopyrightText: Copyright (c) 2024 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

__all__ = ["UpliftParameterWidget"]


from urllib import request, error
import asyncio
import os
import json
import carb
import carb.events
import carb.tokens
import omni.ext
import omni.kit.app
import omni.ui as ui
from omni.ai.viewport.core.abstract_uplift_model import AbstractUpliftModel
from omni.ui import color as cl
import omni.usd
from pxr import Sdf, Usd, UsdGeom, UsdShade
from ..config.api_config import SHUTTERSTOCK_API_TOKEN, MAX_ATTEMPTS, RETRY_DELAY



class ExpandablePrompt:
    """A widget that provides an expandable prompt field."""

    def __init__(self, text_model: ui.SimpleStringModel) -> None:
        """Initialize the ExpandablePrompt.

        Args:
            text_model (ui.SimpleStringModel): The model for the text content.
        """
        self._state = True  # True: Collapsed, False: Expand
        self._text_model = text_model
        self._frame = ui.Frame(build_fn=self._build_fn)

    def _build_fn(self):
        """Build the UI components of the expandable prompt."""
        with ui.ZStack(height=0):
            self._text_field = ui.StringField(
                self._text_model,
                height=25 if self._state else 80,
                multiline=not self._state,
                name="PandoraCatalogFormInput",
            )
            self._expand_button = ui.Button(
                "+" if self._state else "-",
                width=20,
                clicked_fn=self._toggle,
                name="PandoraCatalogFormInput",
            )

    def _toggle(self):
        """Toggle the expanded/collapsed state of the prompt."""
        self._state = not self._state
        self._frame.rebuild()


class Label:
    def __init__(self, text, **kwargs):
        name = kwargs.pop("name", "label")
        self.__label = ui.Label(text, **kwargs, name=name)


class ComboBox:
    def __init__(self, *args, **kwargs):
        name = kwargs.pop("name", "PandoraCatalogSelect")
        with ui.ZStack():
            ui.Rectangle(style_type_name_override="ComboBox", name=name)
            self.__combo = ui.ComboBox(
                *args,
                **kwargs,
                name=name,
                style={
                    "background_color": cl.transparent,
                    "border_color": cl.transparent,
                    "secondary_color": cl.transparent,
                    "color": cl.transparent,
                },
            )

            with ui.HStack():
                label = ui.Label(
                    "",
                    style_type_name_override="ComboBox.Label",
                    name=name,
                )
                ui.Image(width=35, style_type_name_override="ComboBox.Arrow", name=name)

            def set_text(label, model):
                n = model.get_item_value_model().get_value_as_int()
                item = model.get_item_children()[n]
                text = model.get_item_value_model(item).as_string
                label.text = text

            set_text(label, self.__combo.model)
            self.__combo.model.add_item_changed_fn(lambda m, i, l=label: set_text(l, m))

    @property
    def model(self):
        return self.__combo.model


class Separator:
    def __init__(self, **kwargs):
        style_type_name_override = kwargs.pop("style_type_name_override", "Separator")
        style = kwargs.pop("style", {"background_color": cl.transparent})
        ui.Spacer(width=0, height=0, style_type_name_override=style_type_name_override, style=style, **kwargs)


class Info:
    def __init__(
        self, tooltip_heading="Heading", tooltip_hint="tip", tooltip="Lorem ipsum dolor sit amet, consectetur", **kwargs
    ):
        self.__name = kwargs.pop("name", "additional")

        self.__tooltip_heading = tooltip_heading
        self.__tooltip_hint = tooltip_hint
        self.__tooltip = tooltip

        # TODO: Add the correct icon, this is "\u24D8"
        with ui.ZStack(tooltip_fn=lambda: self._tooltip_fn()):
            ui.Circle(name=self.__name)
            ui.Label("i", **kwargs, name=self.__name)

    def _tooltip_fn(self):
        with ui.VStack(width=0, height=0):
            with ui.HStack():
                ui.Label(self.__tooltip_heading, name="tooltipHeading", width=0)
                Separator()
                ui.Label(self.__tooltip_hint, name="tooltipHint", width=0)
            Separator()
            ui.Label(self.__tooltip, name="tooltip")


class RoundButton:
    def __init__(self, text, **kwargs):
        name = kwargs.pop("name", "PandoraCatalogButton")

        with ui.ZStack(width=0, height=0):
            with ui.HStack():
                Separator()
                Separator()
                with ui.ZStack():
                    with ui.ZStack():
                        ui.Circle(style_type_name_override="Button", name=name, alignment=ui.Alignment.LEFT_CENTER)
                        ui.Circle(style_type_name_override="Button", name=name, alignment=ui.Alignment.RIGHT_CENTER)
                        ui.Rectangle(style_type_name_override="Button", name=name, style={"border_radius": 0})
                Separator()
                Separator()

            ui.Button(text, name=name, style={"background_color": ui.color.transparent}, **kwargs)


class UpliftParameterWidget:
    def __init__(
        self,
        uplift_model: AbstractUpliftModel,
        auto_update_model: ui.SimpleBoolModel,
        uplift_cb,
    ):
        self._auto_update_model = auto_update_model
        self._uplift_model = uplift_model
        self._uplift_cb = uplift_cb
        self._frame = ui.Frame(build_fn=self._build_fn, height=0)
        self._tasks = []  # Keep track of running tasks

    def destroy(self):
        """Clean up resources when the widget is destroyed."""
        # Cancel any running async tasks
        for task in self._tasks:
            task.cancel()
        self._tasks.clear()

        # Destroy the frame
        if self._frame:
            self._frame.destroy()
            self._frame = None

    def set_uplift_model(self, uplift_model: AbstractUpliftModel):
        self._uplift_model = uplift_model
        # Trigger a rebuild of the content
        self._frame.rebuild()

    def change_display(self, combo_model, _):
        v = combo_model.get_item_value_model().get_value_as_int()
        new_payload = {"variant": "Display1"}
        if v == 1:
            new_payload["variant"] = "Display2"

        _sender_id = carb.events.acquire_events_interface().acquire_unique_sender_id()
        new_event_type = carb.events.type_from_string("setDisplayVariant")
        bus = omni.kit.app.get_app().get_message_bus_event_stream()
        bus.push(new_event_type, sender=_sender_id, payload=new_payload)

    def change_cup(self, combo_model, _):
        v = combo_model.get_item_value_model().get_value_as_int()
        new_payload = {"variant": "Glass_Mug"}
        if v == 1:
            new_payload["variant"] = "Espresso_Cup"
        elif v == 2:
            new_payload["variant"] = "Coffee_Mug"

        _sender_id = carb.events.acquire_events_interface().acquire_unique_sender_id()
        new_event_type = carb.events.type_from_string("setCupVariant")
        bus = omni.kit.app.get_app().get_message_bus_event_stream()
        bus.push(new_event_type, sender=_sender_id, payload=new_payload)

    def change_machine(self, combo_model, _):
        v = combo_model.get_item_value_model().get_value_as_int()
        new_payload = {"variant": "Black"}
        if v == 1:
            new_payload["variant"] = "Blue"
        elif v == 2:
            new_payload["variant"] = "Cream"
        elif v == 3:
            new_payload["variant"] = "Olive"

        _sender_id = carb.events.acquire_events_interface().acquire_unique_sender_id()
        new_event_type = carb.events.type_from_string("setColorVariant")
        bus = omni.kit.app.get_app().get_message_bus_event_stream()
        bus.push(new_event_type, sender=_sender_id, payload=new_payload)

    def change_env(self, combo_model, _):
        """Change the environment variant based on combo box selection."""
        v = combo_model.get_item_value_model().get_value_as_int()
        new_payload = {"variant": "Lake_view"}  # Default variant

        # Map index to variant name
        variant_map = {
            0: "Lake_view",
            1: "Lookout",
            2: "Edify",
            3: "None"
        }

        if v in variant_map:
            new_payload["variant"] = variant_map[v]

        # print(f"\nChanging environment variant:")
        # print(f"Selected index: {v}")
        # print(f"Sending payload: {new_payload}")

        try:
            _sender_id = carb.events.acquire_events_interface().acquire_unique_sender_id()
            new_event_type = carb.events.type_from_string("setBackdropVariant")
            bus = omni.kit.app.get_app().get_message_bus_event_stream()
            bus.push(new_event_type, sender=_sender_id, payload=new_payload)
            print(f"✓ Event sent: setBackdropVariant with variant '{new_payload['variant']}'")
        except Exception as e:
            print(f"❌ Error sending backdrop variant event: {str(e)}")

    def switch_to_edify(self):
        _sender_id = carb.events.acquire_events_interface().acquire_unique_sender_id()
        new_event_type = carb.events.type_from_string("setBackdropVariant")
        bus = omni.kit.app.get_app().get_message_bus_event_stream()
        bus.push(new_event_type, sender=_sender_id, payload={"variant": "Edify"})
        print("✓ Switched to Edify variant")

    def check_generation_status(self, generation_id):
        """Check the status of a generation request and return panorama URL if ready."""
        api_token = SHUTTERSTOCK_API_TOKEN
        url = f"https://api.shutterstock.com/v2/ai-generated/{generation_id}"
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_token}"
        }

        try:
            req = request.Request(url, headers=headers, method='GET')
            with request.urlopen(req) as response:
                response_data = json.loads(response.read().decode('utf-8'))

                if response_data.get("status") == "completed":
                    # Look for panorama URL in output
                    for output_item in response_data.get("output", []):
                        if output_item.get("type") == "panorama":
                            return output_item.get("url")
                return None

        except Exception as e:
            print(f"Error checking generation status: {str(e)}")
            return None

    async def call_shutterstock_api(self, prompt_text):
        """Call Shutterstock API to get AI generated panorama."""
        if not prompt_text or prompt_text.strip() == "" or prompt_text.upper() == "ENTER A PROMPT":
            return

        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {SHUTTERSTOCK_API_TOKEN}"
        }

        data = {
            "prompt": prompt_text,
            "input_images": [],
            "options": {
                "top_prompt": "Blue sky",
                "bottom_prompt": "Solid ground"
            }
        }

        target_dir = os.path.join("source", "extensions", "omni.conditioning_for_precise_visual_generative_ai.setup",
                                "data", "Collected_EspressoMachine_Asset", "hdri")
        target_path = os.path.join(target_dir, "edify.hdr")

        try:
            os.makedirs(target_dir, exist_ok=True)

            req = request.Request(
                "https://api.shutterstock.com/v2/ai-generated/text-to-panorama",
                data=json.dumps(data).encode('utf-8'),
                headers=headers,
                method='POST'
            )

            with request.urlopen(req) as response:
                response_data = json.loads(response.read().decode('utf-8'))
                generation_id = response_data.get("id")
                if not generation_id:
                    return

            for attempt in range(MAX_ATTEMPTS):
                print(f"Still generating... waiting {RETRY_DELAY} seconds")
                panorama_url = self.check_generation_status(generation_id)

                if panorama_url:
                    try:
                        req = request.Request(panorama_url, headers={'User-Agent': 'Mozilla/5.0'})
                        with request.urlopen(req) as response, open(target_path, 'wb') as out_file:
                            data = response.read()
                            out_file.write(data)
                            out_file.flush()
                            os.fsync(out_file.fileno())

                        if os.path.exists(target_path) and os.path.getsize(target_path) > 0:
                            app = omni.kit.app.get_app()
                            context = omni.usd.get_context()
                            stage = context.get_stage()
                            print(f"\nGenerated HDR URL: {panorama_url}")
                            app = omni.kit.app.get_app()

                            if stage:
                                stage_path = context.get_stage_url()
                                context.open_stage(stage_path)

                                for _ in range(30):
                                    await app.next_update_async()

                                self.switch_to_edify()
                            return
                    except Exception as e:
                        return

                await asyncio.sleep(RETRY_DELAY)

        except Exception as e:
            return

    def _build_fn(self):
        params = self._uplift_model.get_parameters_spec()
        title = "Espresso Machine Configuration"
        with ui.VStack(height=0, spacing=3):

            with ui.HStack(height=25):
                Label(title, name="sceneTitle")
                ui.Spacer(height=0)
                RoundButton(
                    "Run",
                    width=90,
                    clicked_fn=self._uplift_cb,
                )

            with ui.HStack(height=25, separate_window=True, content_clipping=True):
                """Build the Display Type Label"""
                with ui.VStack(height=0, spacing=3):
                    with ui.HStack(width=0):
                        Label("Display types")
                        Separator()
                        Info(tooltip_heading="Text search", tooltip="This sets the USD Variant Set for different control types on the espresso machine.")
                    combo = ComboBox(
                        1,
                        "Analog",
                        "Touch Screen",
                        arrow_only=False,
                    )
                    combo.model.add_item_changed_fn(self.change_display)

                Separator()
                """Build the Cup Type Label"""
                with ui.VStack(height=0, spacing=3):
                    with ui.HStack(width=0):
                        Label("Cup type")
                        Separator()
                        Info(tooltip_heading="Text search", tooltip="This sets the USD Variant Set for different type of mugs that are set on the espresso machine.")
                    combo = ComboBox(
                        0,
                        "Glass Mug",
                        "Espresso Cup",
                        "Coffee Mug",
                        arrow_only=False,
                    )
                    combo.model.add_item_changed_fn(self.change_cup)

            Separator()
            """Build the Machine Color Label"""
            with ui.HStack(height=25, separate_window=True, content_clipping=True):
                with ui.VStack(height=0, spacing=3):
                    with ui.HStack(width=0):
                        Label("Machine color")
                        Separator()
                        Info(tooltip_heading="Text search", tooltip="This sets the USD Variant Set for different colors on the espresso machine.")
                    combo = ComboBox(
                        0,
                        "Black",
                        "Blue",
                        "Cream",
                        "Olive",
                        arrow_only=False,
                    )
                    combo.model.add_item_changed_fn(self.change_machine)

                Separator()
                """Build the Environment HDRI Label"""
                with ui.VStack(height=0, spacing=3):
                    with ui.HStack(width=0):
                        Label("Environment HDRI")
                        Separator()
                        Info(tooltip_heading="Text search", tooltip="This sets the USD Variant Set for different HDR images used beyond the window of the scene. These were generated using Edify360.")

                # COMMENT OUT THIS SECTION
                    # """Build the Dropdown for Environment HDRI"""
                    # combo = ComboBox(
                    #     0,
                    #     "Lake View",
                    #     "Lookout",
                    #     "Edify",
                    #     "None",
                    #     arrow_only=False,
                    # )
                    # combo.model.add_item_changed_fn(self.change_env)
                # END OF COMMENT OUT SECTION


                # UNCOMMENT OUT THIS SECTION FOR EDIFY PROMPT
                    """Build the prompt field and run button for EDIFY Prompt."""
                    with ui.HStack():
                        self._string_model = ui.SimpleStringModel("")
                        field = ui.StringField(self._string_model, height=25, placeholder="Enter your prompt here")
                        self._run_button = ui.Button(
                            "Run",
                            width=90,
                            clicked_fn=lambda: asyncio.ensure_future(self.run_async_handler()),
                            style={"Button": {"border_radius": 20},"background_color": 0x7600FFb9 }
                        )
                # END OF UNCOMMENT OUT SECTION


            Separator()
            Separator()
            Label("Composition Prompts", name="sceneTitle")
            Separator()
            for param in params:
                self._build_param(param)

                Separator()

    def _build_float_param(self, param):
        param_model = ui.SimpleFloatModel(param["default_value"])
        param_model.add_value_changed_fn(
            lambda value, name=param["name"]: self._uplift_model.set_parameters(name, "float", value.as_float)
        )
        ui.FloatSlider(model=param_model)

    def _build_int_param(self, param):
        param_model = ui.SimpleIntModel(param["default_value"])
        param_model.add_value_changed_fn(
            lambda value, name=param["name"]: self._uplift_model.set_parameters(name, "int", value.as_int)
        )
        ui.IntSlider(model=param_model)

    def _build_string_param(self, param):
        param_model = ui.SimpleStringModel(param["default_value"])
        param_model.add_value_changed_fn(
            lambda value, name=param["name"]: self._uplift_model.set_parameters(name, "string", value.as_string)
        )
        ExpandablePrompt(param_model)

    def _build_image_path_param(self, param):
        param_model = ui.SimpleStringModel(param["default_value"])
        param_model.add_value_changed_fn(
            lambda value, name=param["name"]: self._uplift_model.set_parameters(name, "image_path", value.as_string)
        )
        ExpandablePrompt(param_model)


# Build the parameter UI
    def _build_param(self, param):
        with ui.VStack(height=0):

            if param["type"] == "float":
                with ui.HStack(width=0):
                    Label(param["control_name"], alignment=ui.Alignment.TOP)
                    Separator()
                    Info(tooltip_heading="Heading", tooltip=param["default_value"])
                self._build_float_param(param)
            elif param["type"] == "int":
                with ui.HStack(width=0):
                    Label(param["control_name"], alignment=ui.Alignment.TOP)
                    Separator()
                    Info(tooltip_heading="Heading", tooltip=param["default_value"])
                self._build_int_param(param)
            elif param["type"] == "string":
                with ui.HStack(width=0):
                    Label(param["control_name"], alignment=ui.Alignment.TOP)
                    Separator()
                    Info(tooltip_heading="Heading", tooltip=param["description"])
                self._build_string_param(param)
            elif param["type"] == "image_path":
                with ui.HStack(width=0):
                    Label(param["control_name"], alignment=ui.Alignment.TOP)
                    Separator()
                    Info(tooltip_heading="Heading", tooltip=param["default_value"])
                self._build_image_path_param(param)
            elif param["type"] == "float":
                with ui.HStack(width=0):
                    Label(param["control_name"], alignment=ui.Alignment.TOP)
                    Separator()
                    Info(tooltip_heading="Heading", tooltip=param["default_value"])
                self._build_float_param(param)

    async def run_async_handler(self):
        """Handle async operations and keep track of tasks."""
        try:
            # Disable button and change text
            self._run_button.enabled = False
            self._run_button.text = "Running..."

            # Call the API
            await self.call_shutterstock_api(self._string_model.get_value_as_string())

        finally:
            # Restore button state
            self._run_button.enabled = True
            self._run_button.text = "Run"

            # Cleanup
            self._string_model = None
            self._combo_model = None
