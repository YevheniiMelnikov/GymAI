from enum import Enum, auto


class AutoName(str, Enum):
    @staticmethod
    def _generate_next_value_(name: str, start: int, count: int, last_values: list[str]) -> str:
        return name


class ButtonText(AutoName):
    female = auto()
    male = auto()

    quit = auto()
    done = auto()
    select = auto()
    prev_menu = auto()
    pay = auto()
    ask_ai = auto()
    ask_ai_again = auto()
    create_diet = auto()
    diet_again = auto()
    confirm_generate = auto()
    main_menu = auto()

    my_profile = auto()
    my_program = auto()
    top_up = auto()
    subscription_1_month = auto()
    subscription_6_months = auto()
    subscription_12_months = auto()

    faq = auto()

    beginner = auto()
    intermediate = auto()
    advanced = auto()
    experienced = auto()
    gym_workout = auto()
    home_workout = auto()

    view = auto()
    weekly_survey_answer = auto()

    answer_yes = auto()
    answer_no = auto()
    plant_food = auto()
    meat = auto()
    fish_seafood = auto()
    eggs = auto()
    dairy = auto()

    def __str__(self) -> str:
        return f"buttons.{self.name}"


class MessageText(AutoName):
    invalid_content = auto()
    unexpected_error = auto()
    coach_agent_error = auto()

    default_status = auto()
    request_in_progress = auto()
    waiting_for_text = auto()
    choose_gender = auto()
    born_in = auto()
    workout_goals = auto()
    workout_location = auto()
    weight = auto()
    height = auto()
    workout_experience = auto()
    health_notes = auto()
    health_notes_question = auto()
    diet_allergies_question = auto()
    diet_allergies = auto()
    diet_products = auto()
    diet_service_intro = auto()

    finish_registration = auto()
    confirm_service = auto()
    weekly_survey_submitted = auto()

    profile_deleted = auto()
    accept_policy = auto()
    your_data_updated = auto()
    select_language = auto()

    weekly_survey_prompt = auto()

    payment_success = auto()
    payment_failure = auto()
    payment_in_progress = auto()
    contract_info_message = auto()
    follow_link = auto()
    main_menu = auto()
    start = auto()
    saved = auto()
    ask_ai_response_template = auto()
    diet_response_template = auto()

    ask_ai_prompt = auto()
    out_of_range = auto()
    new_workout_plan = auto()
    program_updated = auto()
    subscription_created = auto()

    credit_balance_menu = auto()
    not_enough_credits = auto()
    initial_credits_granted = auto()

    def __str__(self) -> str:
        return f"messages.{self.name}"
