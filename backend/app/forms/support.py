from flask_wtf import FlaskForm
from wtforms import SelectField, StringField, SubmitField, TextAreaField
from wtforms.validators import DataRequired, Length


class SupportRequestForm(FlaskForm):
    subject = StringField("Subject", validators=[DataRequired(), Length(min=3, max=150)])
    category = SelectField(
        "Category",
        choices=[
            ("account", "Account"),
            ("claim", "Claims"),
            ("item", "Items"),
            ("workspace", "Workspace"),
            ("billing", "Billing"),
            ("other", "Other"),
        ],
        validators=[DataRequired()],
    )
    message = TextAreaField("Message", validators=[DataRequired(), Length(min=20, max=4000)])
    submit = SubmitField("Submit request")


class SupportResolveForm(FlaskForm):
    resolution_notes = TextAreaField("Resolution notes", validators=[DataRequired(), Length(min=10, max=4000)])
    submit = SubmitField("Mark resolved")
